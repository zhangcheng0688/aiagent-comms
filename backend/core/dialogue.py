"""多轮对话引擎 V2.0：LLM 驱动策略选择 + 完整降级路径。

协商循环：
1. 逐项确认诉求
2. 商家反提案 → 进入 NEGOTIATING
3. 在 NEGOTIATING 内：
   - 优先调 LLM 决策下一步策略 + 生成话术
   - LLM 不可用 → 降级 V1.2 规则
   - 优先 LLM 判断商家是否让步
   - LLM 不可用 → 降级 V1.2 关键词
4. 升级阈值场景化
"""
from __future__ import annotations
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Optional

log = logging.getLogger("aiagent.dialogue")
from ..config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL, DIALOGUE_COMPRESS_THRESHOLD, NEGOTIATION_SESSION_TIMEOUT
from ..models import (
    Order, OrderState, OrderStatus, DialogueTurn, IntentSlot
)
from .state_machine import next_state
from .translator import translate
from .negotiation import (
    NegotiationContext, should_escalate, detect_constraints,
    record_strategy_result,
)
from .llm_negotiator import (
    decide_next_move, assess_outcome, fallback_strategy_decision,
    fallback_outcome_assessment, _scenario_value_added,
)
from .compressor import compress_dialogue, split_for_context  # 1.7.3
from .progress_notifier import ProgressNotifier, get_smtp_creds  # 1.7.4
from ..channels.voice import VoiceChannel
from ..channels.sms import SmsChannel
from ..knowledge import (
    hotel_templates, car_rental_templates, flight_templates
)

TEMPLATES = {
    "hotel": hotel_templates,
    "car_rental": car_rental_templates,
    "flight": flight_templates,
}


class DialogueEngine:
    def __init__(self, voice: VoiceChannel, sms: SmsChannel, on_turn=None):
        """
        on_turn: 每轮对话结束（AI + merchant 一对 turn）的回调，签名 async (order)
                 用于主进程实时更新 DB / 推送 WS。
        """
        self.voice = voice
        self.sms = sms
        self.on_turn = on_turn

    async def _fire_on_turn(self, order: Order):
        if self.on_turn:
            try:
                await self.on_turn(order)
            except Exception as e:
                log.warning(f"on_turn callback failed: {e}")

    async def run(self, order: Order) -> Order:
        lang = order.target_language
        scenario = order.scenario
        templates = TEMPLATES.get(scenario, hotel_templates)

        order.state = next_state(order.state, "submit") or order.state

        if scenario == "flight":
            await self._penetrate_ivr(order, lang, templates)
        else:
            await self._normal_open(order, lang, templates)

        round_count = 0
        for intent in sorted(order.intents, key=lambda i: i.priority):
            ai_ask = templates.get_template("confirm", lang, item=intent.description)
            merchant_text = await self._send_and_receive(order, ai_ask, lang, scenario)
            round_count += 1

            is_proposal, proposal_data = self._parse_merchant_reply(merchant_text, intent, lang, scenario)

            if is_proposal and proposal_data:
                intent.confirmed_value = f"待协商（商家提加价 {proposal_data.get('price_change_pct', 0):.0f}%）"
                negotiated = await self._negotiate(order, intent, proposal_data, lang, scenario, templates, round_count)
                if negotiated == "escalated":
                    return order
                elif negotiated == "failed":
                    return order
                else:
                    intent.confirmed_value = negotiated

        ai_close = templates.get_template("close_success", lang, summary=order.requirement[:50])
        await self._send_and_receive(order, ai_close, lang, scenario)
        order.state = OrderState.CLOSING_SUCCESS
        order.status = OrderStatus.SUCCESS

        scenario_label = {"hotel": "酒店", "car_rental": "租车", "flight": "机票"}.get(scenario, "出行")
        order.result = {
            "summary": f"已与{order.organization}完成{len(order.intents)}项{scenario_label}代办确认",
            "scenario": scenario,
            "confirmed_intents": [
                {"slot_id": i.slot_id, "type": i.type, "value": i.confirmed_value or i.target_value}
                for i in order.intents
            ],
            "receipt": {
                "channel": order.preferred_channel.value,
                "language": lang,
                "rounds": round_count,
                "mock": True,
                # 真 LLM = LLM_API_KEY 非占位符 OR MAVIS_ACCESS_TOKEN 存在
                "llm_driven": bool(
                    (LLM_API_KEY and LLM_API_KEY != "sk-xxx")
                    or os.getenv("MAVIS_ACCESS_TOKEN")
                ),
            },
            "next_steps": _scenario_next_steps(scenario, order.organization),
        }
        return order

    async def _normal_open(self, order: Order, lang: str, templates) -> None:
        ai_open = templates.get_template("open", lang, user_name="Alex", company=order.organization)
        await self._send_and_receive(order, ai_open, lang, order.scenario)
        order.state = next_state(order.state, "connected") or order.state
        order.state = next_state(order.state, "merchant_ready") or order.state

    async def _penetrate_ivr(self, order: Order, lang: str, templates) -> None:
        ivr_hint_text = templates.get_template("ivr_hint", lang)
        await self._send_and_receive(order, ivr_hint_text, lang, order.scenario)
        order.state = next_state(order.state, "connected") or order.state
        order.state = next_state(order.state, "merchant_ready") or order.state

    async def _negotiate(
        self, order: Order, intent: IntentSlot, proposal_data: dict, lang: str,
        scenario: str, templates, initial_round: int
    ) -> str:
        """V2.0 协商循环（1.7 升级）：20 轮 + 摘要压缩 + 进度通知 + 暂停/恢复。"""
        import os
        # 1.7.5 长路径：把加价 % 压到 5%，让 AI 多轮谈
        if os.getenv("AIAGENT_LONG_TALK") == "1" or "长沟通" in order.requirement:
            proposal_data = dict(proposal_data)
            proposal_data["price_change_pct"] = 5.0
            proposal_data["price_change_abs"] = 100
            proposal_data["summary"] = "Manager still reviewing. Will reply in a moment."
        ctx = NegotiationContext(
            scenario=scenario,
            round_count=initial_round,
            user_constraints=order.constraints,
            price_change_pct=proposal_data.get("price_change_pct", 0),
            price_change_abs=proposal_data.get("price_change_abs", 0),
            last_merchant_text=str(proposal_data.get("summary", "")),
            last_strategy_id=None,
            tried_strategies=[],
            bundle_items=_scenario_bundle(scenario, lang, intent),
        )

        order.state = next_state(order.state, "merchant_pushback") or OrderState.NEGOTIATING
        order.state = next_state(order.state, "probe") or order.state

        # 1.7 升级：max_loops 跟 config 走，1.7.1 默认 20
        from ..config import MAX_NEGOTIATION_ROUNDS
        max_loops = MAX_NEGOTIATION_ROUNDS
        last_strategy_id = None
        last_ai_speech = None

        # 1.7.4 进度通知
        notifier = None
        smtp_user, smtp_password = get_smtp_creds()
        if smtp_user and smtp_password:
            try:
                notifier = ProgressNotifier(
                    smtp_user=smtp_user,
                    smtp_password=smtp_password,
                    customer_email=order.user_email or "",  # type: ignore[attr-defined]
                    order_id=order.id,
                    organization=order.organization,
                )
            except Exception as e:
                log.warning(f"notifier init failed: {e}")

        # 1.7.3 摘要缓存
        cached_summary = ""
        compressed_at_round = 0

        try:
            for loop_idx in range(max_loops):
                # 1.7.3 摘要压缩触发
                if len(order.dialogue) >= DIALOGUE_COMPRESS_THRESHOLD and not cached_summary:
                    log.info(f"compressing {len(order.dialogue)} turns at round {loop_idx}")
                    cached_summary = await compress_dialogue(
                        [
                            {"speaker": t.speaker, "original": t.original, "translated": t.translated}
                            for t in order.dialogue
                        ],
                        scenario=scenario,
                    )
                    compressed_at_round = loop_idx

                # 构造对话历史喂给 LLM（带摘要）
                if cached_summary:
                    recent_turns = [
                        {"speaker": t.speaker, "text": t.original, "lang": lang}
                        for t in order.dialogue[-12:]  # 最近 6 轮
                    ]
                    full_dialogue = (
                        [{"speaker": "summary", "text": cached_summary, "lang": "zh"}]
                        + recent_turns
                    )
                else:
                    full_dialogue = [
                        {"speaker": t.speaker, "text": t.original, "lang": lang}
                        for t in order.dialogue[-12:]
                    ]

                # 1. 检查升级阈值
                should_esc, reason = should_escalate(ctx)
                if should_esc:
                    order.state = next_state(order.state, "escalation_triggered") or order.state
                    order.result = {
                        "negotiation_required": True,
                        "reason": reason,
                        "proposal": proposal_data,
                        "round_count": ctx.round_count,
                        "scenario": scenario,
                        "tried_strategies": ctx.tried_strategies,
                        "engine": "V2.0 LLM-driven (1.7 long-talk)",
                    }
                    return "escalated"

                # 2. 决策下一步（LLM → 降级 V1.2）
                strategy_id, ai_text, reasoning = await decide_next_move(
                    full_dialogue, ctx, order.requirement, order.constraints, lang, order.organization
                )

                if strategy_id == "escalate":
                    order.state = next_state(order.state, "escalation_triggered") or order.state
                    order.result = {
                        "negotiation_required": True,
                        "reason": reasoning or "LLM 决定升级",
                        "proposal": proposal_data,
                        "round_count": ctx.round_count,
                        "tried_strategies": ctx.tried_strategies,
                    }
                    return "escalated"

                last_strategy_id = strategy_id
                last_ai_speech = ai_text
                order.dialogue.append(DialogueTurn(
                    turn_id=len(order.dialogue) + 1, speaker="ai",
                    original=ai_text, translated=ai_text, timestamp=datetime.utcnow(),
                ))

                # 3. 商家回复
                merchant_reply = await self._call_merchant(order, ai_text, lang, scenario)
                merchant_zh = await translate(merchant_reply, target="zh", source=lang)
                order.dialogue.append(DialogueTurn(
                    turn_id=len(order.dialogue) + 1, speaker="merchant",
                    original=merchant_reply, translated=merchant_zh, timestamp=datetime.utcnow(),
                ))

                # 4. 判断商家是否让步
                outcome = await assess_outcome(
                    strategy_id, ai_text, merchant_reply, ctx.price_change_pct, ctx.price_change_abs, lang
                )
                outcome_result = outcome.get("outcome", "neutral")
                new_pct = float(outcome.get("new_price_pct", ctx.price_change_pct))
                new_abs = float(outcome.get("new_price_abs", ctx.price_change_abs))

                # 5. 更新 ctx
                ctx = record_strategy_result(
                    ctx, strategy_id, merchant_reply, new_pct, new_abs
                )
                order.state = next_state(order.state, "counter_offer") or order.state

                # 1.7.4 进度通知（节流：60s 一次）
                if notifier and notifier.maybe_notify(
                    current_round=ctx.round_count,
                    last_strategy=strategy_id,
                    last_merchant_text=merchant_reply,
                    state=order.state.value,
                ):
                    pass  # 邮件已发

                # 6. 检查结果
                if outcome_result == "success":
                    order.state = next_state(order.state, "compromise_reached") or OrderState.CLOSING_SUCCESS
                    return f"达成：{strategy_id}（{reasoning}）"
                elif outcome_result == "failed":
                    if strategy_id == "walk_away":
                        order.state = next_state(order.state, "walk_away") or OrderState.CLOSING_FAILURE
                        return "failed"
                    continue

            # 超过 max_loops
            order.state = next_state(order.state, "escalation_triggered") or order.state
            order.result = {
                "negotiation_required": True,
                "reason": f"协商 {max_loops} 轮无果（1.7 升级阈值）",
                "proposal": proposal_data,
                "round_count": ctx.round_count,
                "tried_strategies": ctx.tried_strategies,
            }
            return "escalated"
        finally:
            if notifier:
                notifier.close()

    async def _call_merchant(self, order: Order, ai_text: str, lang: str, scenario: str) -> str:
        """根据用户偏好通道调商家。"""
        import os
        # 1.7.5 长路径模式：商家反复"还在 check"，让 AI 持续换策略。
        # 配合 order.dialogue 长度计数，第 N 轮才让步。
        if os.getenv("AIAGENT_LONG_TALK") == "1" or "长沟通" in order.requirement:
            ai_turns = sum(1 for t in order.dialogue if t.speaker == "ai")
            # 让步阈值：超过 12 轮才让步
            if ai_turns >= 12:
                return "OK, I can offer a 10% discount. That will be our final price."
            # 中间轮：商家反应按轮次递进
            if ai_turns <= 3:
                return "Let me check with my manager on the rate. I will reply to you in a moment."
            if ai_turns <= 6:
                return "I checked. Our best is 5% off the original rate. The manager is reviewing further requests."
            if ai_turns <= 9:
                return "OK, I can move another 2% down, but the manager said this is already very close to the floor."
            return "Let me ask the manager one more time..."
        if order.preferred_channel.value == "voice":
            return await self.voice.call(order.contact_number, ai_text, lang)
        return await self.sms.send(order.contact_number, ai_text)

    async def _send_and_receive(self, order: Order, ai_text: str, lang: str, scenario: str) -> str:
        merchant_text = await self._call_merchant(order, ai_text, lang, scenario)
        merchant_zh = await translate(merchant_text, target="zh", source=lang)
        order.dialogue.append(DialogueTurn(
            turn_id=len(order.dialogue) + 1, speaker="merchant",
            original=merchant_text, translated=merchant_zh, timestamp=datetime.utcnow(),
        ))
        order.updated_at = datetime.utcnow()
        # 1.7.5 实时进度：每轮对话结束触发回调
        await self._fire_on_turn(order)
        return merchant_text

    def _parse_merchant_reply(
        self, merchant_text: str, intent: IntentSlot, lang: str, scenario: str
    ) -> tuple[bool, dict | None]:
        text_lower = merchant_text.lower()
        upgrade_keywords = {
            "hotel": {
                "en": ["fully booked", "only have", "additional", "upgrade", "deluxe", "sold out",
                       "manager", "front desk", "need to confirm", "best is", "5%", "discount",
                       "reviewing", "floor", "close to"],  # 1.7.5 触发长协商
                "ja": ["満室", "追加料金", "デラックス", "アップグレード", "満車"],
                "ko": ["만실", "추가 요금", "디럭스", "업그레이드", "만석"],
            },
            "car_rental": {
                "en": ["sold out", "only have", "compact suv", "upgrade", "surcharge", "one-way"],
                "ja": ["満車", "コンパクトSUV", "アップグレード", "追加料金", "片道料金"],
                "ko": ["만석", "컴팩트 SUV", "업그레이드", "추가 요금", "편도 요금"],
            },
            "flight": {
                "en": ["fare difference", "25,000", "95,000", "38,000", "peak season", "non-refundable", "満席", "만석"],
                "ja": ["差額", "繁忙期", "25,000", "95,000", "不可", "満席"],
                "ko": ["차액", "성수기", "25,000", "95,000", "불가", "만석"],
            },
        }
        is_proposal = any(kw in text_lower for kw in upgrade_keywords.get(scenario, upgrade_keywords["hotel"]).get(lang, []))
        if is_proposal:
            return (True, _build_proposal(scenario, lang))
        return (False, None)


def _build_proposal(scenario: str, lang: str) -> dict:
    """（V2.0 同 V1.1）"""
    proposals = {
        "hotel": {
            "en": {
                "summary": "原房型已满，需升级到豪华房，加价 ¥280/晚",
                "options": [
                    {"option_id": "A", "label": "接受升级豪华房", "price_change": "+¥280/晚", "key_changes": ["房型升级", "原早餐保留"]},
                    {"option_id": "B", "label": "改其他日期", "price_change": "0", "key_changes": ["保持原房型", "差一天"]},
                    {"option_id": "C", "label": "保持原状+补偿", "price_change": "0", "key_changes": ["酒店补偿 ¥100"]},
                ],
                "price_change_pct": 25.0, "price_change_abs": 280,
            },
            "ja": {
                "summary": "元のツインルームは満室で、デラックスルームへの変更で追加1泊4,800円が発生します",
                "options": [
                    {"option_id": "A", "label": "デラックスルームにアップグレード", "price_change": "+¥280/晚", "key_changes": ["お部屋タイプUP", "朝食そのまま"]},
                    {"option_id": "B", "label": "日程変更", "price_change": "0", "key_changes": ["元のタイプ維持", "1日シフト"]},
                    {"option_id": "C", "label": "現状維持+補償", "price_change": "0", "key_changes": ["ホテル補償 ¥100"]},
                ],
                "price_change_pct": 25.0, "price_change_abs": 280,
            },
            "ko": {
                "summary": "원래 트윈룸 만실, 디럭스룸 업그레이드 시 1박 4,800원 추가 발생",
                "options": [
                    {"option_id": "A", "label": "디럭스룸 업그레이드 수락", "price_change": "+₩4,800/박", "key_changes": ["객실 업그레이드", "조식 유지"]},
                    {"option_id": "B", "label": "날짜 변경", "price_change": "0", "key_changes": ["원래 타입 유지", "하루 시프트"]},
                    {"option_id": "C", "label": "현상 유지+보상", "price_change": "0", "key_changes": ["호텔 보상 ₩100"]},
                ],
                "price_change_pct": 25.0, "price_change_abs": 280,
            },
        },
        "car_rental": {
            "en": {
                "summary": "Economy is sold out. We only have Compact SUV available, +¥240/day",
                "options": [
                    {"option_id": "A", "label": "Accept Compact SUV upgrade", "price_change": "+¥240/day", "key_changes": ["Vehicle upgrade", "Unlimited mileage unchanged"]},
                    {"option_id": "B", "label": "Try different dates (find Economy)", "price_change": "0", "key_changes": ["Keep economy class", "Shift 1-2 days"]},
                    {"option_id": "C", "label": "Cancel rental", "price_change": "0", "key_changes": ["Full refund"]},
                ],
                "price_change_pct": 41.0, "price_change_abs": 240,
            },
            "ja": {
                "summary": "エコノミークラス満車。コンパクトSUVのみ利用可能、+¥240/日",
                "options": [
                    {"option_id": "A", "label": "コンパクトSUVに変更", "price_change": "+¥240/日", "key_changes": ["車種UP", "走行距離無制限維持"]},
                    {"option_id": "B", "label": "日程変更（エコノミー空き待ち）", "price_change": "0", "key_changes": ["エコノミー維持", "1-2日シフト"]},
                    {"option_id": "C", "label": "キャンセル", "price_change": "0", "key_changes": ["全額返金"]},
                ],
                "price_change_pct": 41.0, "price_change_abs": 240,
            },
            "ko": {
                "summary": "이코노미 만석. 컴팩트 SUV만 가능, +₩3,600/일",
                "options": [
                    {"option_id": "A", "label": "컴팩트 SUV로 변경", "price_change": "+₩3,600/일", "key_changes": ["차종 업그레이드", "무제한 주행거리 유지"]},
                    {"option_id": "B", "label": "날짜 변경 (이코노미 대기)", "price_change": "0", "key_changes": ["이코노미 유지", "1-2일 시프트"]},
                    {"option_id": "C", "label": "취소", "price_change": "0", "key_changes": ["전액 환불"]},
                ],
                "price_change_pct": 41.0, "price_change_abs": 240,
            },
        },
        "flight": {
            "en": {
                "summary": "Date change to peak season: +¥25,000 fare difference + ¥5,000 change fee",
                "options": [
                    {"option_id": "A", "label": "Accept peak season change", "price_change": "+¥30,000", "key_changes": ["New date confirmed", "Seat reserved"]},
                    {"option_id": "B", "label": "Change to off-peak date", "price_change": "0", "key_changes": ["Avoid peak surcharge", "Only ¥5,000 change fee"]},
                    {"option_id": "C", "label": "Refund", "price_change": "0", "key_changes": ["Refund per fare rules"]},
                ],
                "price_change_pct": 25.0, "price_change_abs": 30000,
            },
            "ja": {
                "summary": "繁忙期への変更、航空券差額¥25,000 + 変更手数料¥5,000",
                "options": [
                    {"option_id": "A", "label": "繁忙期変更を承諾", "price_change": "+¥30,000", "key_changes": ["新日程確定", "座席保持"]},
                    {"option_id": "B", "label": "閑散期に変更", "price_change": "0", "key_changes": ["繁忙期回避", "手数料¥5,000のみ"]},
                    {"option_id": "C", "label": "払い戻し", "price_change": "0", "key_changes": ["規定通り返金"]},
                ],
                "price_change_pct": 25.0, "price_change_abs": 30000,
            },
            "ko": {
                "summary": "성수기 변경, 항공권 차액 ₩37,000 + 변경 수수료 ₩7,500",
                "options": [
                    {"option_id": "A", "label": "성수기 변경 수락", "price_change": "+₩44,500", "key_changes": ["새 일정 확정", "좌석 유지"]},
                    {"option_id": "B", "label": "비수기로 변경", "price_change": "0", "key_changes": ["성수기 회피", "수수료 ₩7,500만"]},
                    {"option_id": "C", "label": "환불", "price_change": "0", "key_changes": ["규정에 따라 환불"]},
                ],
                "price_change_pct": 25.0, "price_change_abs": 30000,
            },
        },
    }
    return proposals.get(scenario, proposals["hotel"]).get(lang, proposals[scenario]["en"])


def _scenario_bundle(scenario: str, lang: str, intent: IntentSlot) -> list[str]:
    return {
        "hotel": {"ja": ["朝食", "駐車場", "延泊"], "ko": ["조식", "주차", "연박"], "en": ["breakfast", "parking", "extra night"]},
        "car_rental": {"ja": ["GPS", "追加ドライバー", "幼児シート"], "ko": ["GPS", "추가 운전자", "유아 시트"], "en": ["GPS", "extra driver", "child seat"]},
        "flight": {"ja": ["座席指定", "機内食", "追加手荷物"], "ko": ["좌석 지정", "기내식", "추가 수하물"], "en": ["seat selection", "meal", "extra baggage"]},
    }.get(scenario, {"ja": ["追加サービス"], "ko": ["추가 서비스"], "en": ["additional services"]}).get(lang, ["additional services"])


def _scenario_next_steps(scenario: str, organization: str) -> list[str]:
    common = [f"保留邮件回执截图，{scenario}现场出示", "如有问题可点击联系客服"]
    extra = {
        "hotel": ["到店后核对房间号/早餐券/入住日期", "保留前台邮件回执 PDF"],
        "car_rental": ["到店出示国际驾照 IDP + 中国驾照", "检查保险生效日期", "还车前加满油（避免高额代加油费）"],
        "flight": ["起飞前 24h 在线 check-in", "确认登机口和航站楼", "托运行李称重避免超重费"],
    }
    return extra.get(scenario, common) + [f"关注 {organization} 后续邮件"]

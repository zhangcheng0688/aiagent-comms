"""V2.0 LLM 驱动协商决策器。

让 LLM 看完整对话历史 + 用户约束 + 升级阈值，决策下一步策略 + 生成对应话术。
LLM 不可用时自动降级到 V1.2 规则选择。

支持 MOCK_LLM 环境变量：
- "0" / 不设：调真实 LLM API
- "1"：用预定义的 mock 回复（测试用）

LLM 客户端走 `backend.llm_client.call_mavis_llm`（Anthropic Messages 格式，
Mavis daemon 注入 `Token: <MAVIS_ACCESS_TOKEN>` 头鉴权）。
"""
from __future__ import annotations
import json
import os
import re
from typing import Optional
from ..llm_client import call_mavis_llm, extract_json_from_text
from ..config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL
from .negotiation import NegotiationContext, detect_constraints
from ..knowledge.negotiation_strategies import (
    ALL_STRATEGIES, STRATEGY_BY_ID, SCENARIO_ESCALATION_THRESHOLDS,
    STRATEGY_HOLD, STRATEGY_ALT_DATE, STRATEGY_CHAIN_OFFER, STRATEGY_VALUE_TRADE,
    STRATEGY_LOYALTY, STRATEGY_WALK_AWAY,
)

MOCK_LLM = os.getenv("MOCK_LLM", "0") == "1"


# === Mock LLM 预定义回复 ===
MOCK_LLM_RESPONSES = {
    "default": {
        "strategy_id": "hold_position",
        "ai_speech": "I understand your position, but I have a strict budget constraint. Could you offer any discount or alternative?",
        "reasoning": "用户有预算约束，AI 应坚持立场同时寻求替代",
        "merchant_outcome_guess": "success",
        "new_price_pct_guess": 12,
    },
    "escalate": {
        "strategy_id": "escalate",
        "ai_speech": "I'll need to consult with the customer and get back to you.",
        "reasoning": "加价已超阈值，升级用户决策",
        "merchant_outcome_guess": "failed",
        "new_price_pct_guess": 25,
    },
    "alt_date": {
        "strategy_id": "alt_date",
        "ai_speech": "If that date doesn't work, would 6.13 or 6.14 be possible? I can flex up to a week on either side.",
        "reasoning": "商家说原日期不可，AI 提替代日期",
        "merchant_outcome_guess": "success",
        "new_price_pct_guess": 0,
    },
    "value_trade": {
        "strategy_id": "value_trade",
        "ai_speech": "The room conditions can stay as-is. Could we add the breakfast package as compensation?",
        "reasoning": "商家坚守价格但显灵活，AI 提增值让步",
        "merchant_outcome_guess": "success",
        "new_price_pct_guess": 0,
    },
    "chain_offer": {
        "strategy_id": "chain_offer",
        "ai_speech": "Regarding the upcharge—would you consider keeping the total unchanged if I bundle in extra services?",
        "reasoning": "用户没硬约束，AI 反提案打包换价格",
        "merchant_outcome_guess": "neutral",
        "new_price_pct_guess": 15,
    },
    "loyalty": {
        "strategy_id": "loyalty",
        "ai_speech": "I should mention I'm a repeat customer—do you have a loyalty program I could apply?",
        "reasoning": "第二轮了，AI 尝试用忠诚度换价",
        "merchant_outcome_guess": "success",
        "new_price_pct_guess": 10,
    },
    "walk_away": {
        "strategy_id": "walk_away",
        "ai_speech": "I appreciate your patience, but I won't be able to proceed. Thank you for your time.",
        "reasoning": "已到协商上限，AI 主动离场",
        "merchant_outcome_guess": "failed",
        "new_price_pct_guess": 25,
    },
}


def _mock_llm_response(scenario: str, ctx: NegotiationContext, used_strategies: list) -> dict:
    """根据上下文返回 mock LLM 决策。"""
    # 升级阈值超了 → escalate
    if ctx.price_change_pct > 25 and "escalate" not in used_strategies:
        return MOCK_LLM_RESPONSES["escalate"]
    # 已经用过 3+ 策略还没成 → walk_away
    if len(used_strategies) >= 3:
        return MOCK_LLM_RESPONSES["walk_away"]
    # 第一次：hold_position
    if "hold_position" not in used_strategies:
        return MOCK_LLM_RESPONSES["default"]
    # 第二次：alt_date 或 value_trade
    if "alt_date" not in used_strategies and ctx.price_change_pct > 0:
        return MOCK_LLM_RESPONSES["alt_date"]
    if "value_trade" not in used_strategies:
        return MOCK_LLM_RESPONSES["value_trade"]
    # 第三次：chain_offer
    if "chain_offer" not in used_strategies:
        return MOCK_LLM_RESPONSES["chain_offer"]
    # 第四次：loyalty
    if "loyalty" not in used_strategies:
        return MOCK_LLM_RESPONSES["loyalty"]
    # 全部用完
    return MOCK_LLM_RESPONSES["walk_away"]


# === 策略手册（喂给 LLM 的"剧本"） ===
STRATEGY_MANUAL = """你是一位跨境出行的资深谈判专家，正在帮用户与境外商家（酒店/租车/机票公司）进行多轮沟通。

## 可用策略（按场景）

### 1. hold_position（坚持原条件）
**适用**：用户约束"不可加价"或"保持原价"，且商家提加价。
**话术框架**：礼貌但坚定重申用户约束，请求商家给折扣或替代方案。
**风险**：反复用可能让商家觉得无诚意。

### 2. alt_date（替代日期）
**适用**：商家说原日期已满/不可，主动提相邻日期。
**话术框架**：列 2-3 个候选日期，强调灵活性。
**风险**：用户可能不接受日期调整。

### 3. value_trade（增值让步）
**适用**：商家坚守价格但显灵活（例：语气中允许加订服务）。
**话术框架**：保持原条件不变，但主动加订一项增值服务（早餐/保险/接送等）作为补偿。
**风险**：增值服务用户可能不需要。

### 4. chain_offer（链式反提案）
**适用**：商家提加价后，用户没有"不可加价"硬约束，但商家仍可谈。
**话术框架**：打包多项需求（多订几晚+接送+选座+餐食+保险等）换价格不变或小幅下降。
**风险**：用户可能不需要 bundle 中的某些项。

### 5. loyalty（忠诚度换价）
**适用**：用户可能是回头客/重复客户场景。
**话术框架**：表明自己是频繁入住/租赁的回头客，请求会员价或长租折扣。
**风险**：用户可能不是会员。

### 6. walk_away（提前离场）
**适用**：协商轮数已到上限（4 轮），或商家明显坚持。
**话术框架**：礼貌表示无法继续，结束沟通。
**风险**：完全终止订单。

## 输出要求

你必须返回严格的 JSON 格式：

```json
{
  "strategy_id": "hold_position | alt_date | value_trade | chain_offer | loyalty | walk_away | escalate",
  "ai_speech": "用目标语种（en/ja/ko）写的完整 AI 话术，长度 30-80 字，自然口语化，商务敬语",
  "reasoning": "用中文简要说明为什么选这个策略（1-2 句）",
  "merchant_outcome_guess": "success | failed | neutral",
  "new_price_pct_guess": 0-50
}
```

注意：
- 如果商家最新回复显示明确让步（关键词如 discount/可用/ok/sure/yes/可能です/ご利用いただけます 等），选能"锁定让步"的策略（如 value_trade 来固化，或直接 walk_away 收单）
- 如果商家明确拒绝（cannot/不可/無理/できません/만석/죄송합니다），考虑换 alt_date 或直接 walk_away
- 如果已经 3+ 轮没进展，强烈倾向 walk_away
- 如果价格变化超阈值（酒店 20% / 租车 30% / 机票 ¥30,000），返回 escalate
- 不要重复已经用过的策略（除非它有变体）"""


# === LLM 调用 ===
async def call_llm_for_negotiation(
    full_dialogue: list[dict],
    ctx: NegotiationContext,
    user_requirement: str,
    user_constraints: str | None,
    lang: str,
    organization: str,
) -> Optional[dict]:
    """调 LLM 让它决策 + 生成话术。返回 None 表示 LLM 不可用（降级到 V1.2）。

    full_dialogue 格式：[{speaker: "ai"|"merchant", text: str, lang: str}, ...]
    """
    # Mock 模式
    if MOCK_LLM:
        used = ctx.tried_strategies or []
        return _mock_llm_response(ctx.scenario, ctx, used)

    # 真 LLM 模式：call_mavis_llm 内部会从 LLM_API_KEY 或 MAVIS_ACCESS_TOKEN 拿 token
    # token 都没有时它自己返回 None，所以这里不用提前判

    constraints = detect_constraints(user_constraints)
    threshold = SCENARIO_ESCALATION_THRESHOLDS.get(ctx.scenario, SCENARIO_ESCALATION_THRESHOLDS["hotel"])

    # 构造对话历史（只取最近 10 轮避免 prompt 过长）
    recent = full_dialogue[-10:]
    dialogue_text = "\n".join(
        f"[{t['speaker'].upper()}]" + (f" ({t.get('lang','?')})" if t['speaker']=='merchant' else "") + f" {t['text']}"
        for t in recent
    )

    user_prompt = f"""## 当前任务
- 用户原始需求：{user_requirement}
- 用户约束：{user_constraints or '无'}
- 目标商家：{organization}
- 沟通语种：{lang}
- 场景：{ctx.scenario}
- 当前轮数：{ctx.round_count} / 4
- 商家最近加价：+{ctx.price_change_pct:.0f}% / +{ctx.price_change_abs:.0f} 元
- 该场景升级阈值：{threshold['price_change_pct']}% / {threshold['price_change_abs']} 元
- 用户硬约束：{constraints}
- 已用策略：{ctx.tried_strategies if ctx.tried_strategies else '（首次）'}

## 完整对话历史
{dialogue_text}

## 决策
请决定下一步策略和话术。返回 JSON。"""

    try:
        content = await call_mavis_llm(
            system=STRATEGY_MANUAL,
            user=user_prompt,
            max_tokens=600,
            temperature=0.3,
        )
        if not content:
            return None
        data = extract_json_from_text(content)
        if not data:
            return None
        if data.get("strategy_id") in [s.id for s in ALL_STRATEGIES] + ["escalate"]:
            return data
        return None
    except Exception:
        return None


async def call_llm_for_outcome_assessment(
    strategy_id: str,
    ai_speech: str,
    merchant_text: str,
    original_price_pct: float,
    original_price_abs: float,
    lang: str,
) -> Optional[dict]:
    """让 LLM 判断商家是否让步。返回 {outcome, new_price_pct, new_price_abs, reason} 或 None。"""
    if MOCK_LLM:
        # Mock 模式：根据商家回复关键词判断
        text = merchant_text.lower()
        if any(kw in text for kw in ["discount", "alternative", "consider", "お値引き", "割引", "代替", "検討",
                                    "할인", "대안", "검토", "可用", "ご利用", "이용 가능", "available", "works"]):
            return {
                "outcome": "success",
                "new_price_pct": max(0, original_price_pct * 0.5),
                "new_price_abs": max(0, original_price_abs * 0.5),
                "reason": "MOCK: 商家让步关键词命中",
            }
        if any(kw in text for kw in ["can't", "cannot", "unable", "impossible",
                                    "無理", "できない", "申し訳ございません",
                                    "불가능", "죄송합니다", "안 됩니다"]):
            return {
                "outcome": "failed",
                "new_price_pct": original_price_pct,
                "new_price_abs": original_price_abs,
                "reason": "MOCK: 商家拒绝关键词命中",
            }
        return {
            "outcome": "neutral",
            "new_price_pct": original_price_pct,
            "new_price_abs": original_price_abs,
            "reason": "MOCK: 无明确信号",
        }

    # 真 LLM 模式：call_mavis_llm 内部自己拿 token

    prompt = f"""## 协商评估
- AI 上一句策略：{strategy_id}
- AI 上一句说：{ai_speech}
- 商家最新回复：{merchant_text}
- 当前加价：+{original_price_pct:.0f}% / +{original_price_abs:.0f} 元

请判断商家是否让步，并返回 JSON：

```json
{{
  "outcome": "success | failed | neutral",
  "new_price_pct": 0-50,
  "new_price_abs": 0-{max(int(original_price_abs*2), 1000)},
  "reason": "中文 1-2 句判断理由"
}}
```

- success：商家让步（价格降/同意原条件/提供替代方案/确认优惠）
- failed：商家拒绝（明确不可能/坚持原价/说对不起）
- neutral：模糊（再查查/需要确认/请稍等）——按 failed 处理，换策略"""

    try:
        content = await call_mavis_llm(
            system="你是商务谈判评估专家。只返回 JSON。",
            user=prompt,
            max_tokens=300,
            temperature=0.1,
        )
        if not content:
            return None
        data = extract_json_from_text(content)
        if not data:
            return None
        if data.get("outcome") in ("success", "failed", "neutral"):
            return data
        return None
    except Exception:
        return None


# === 降级到 V1.2 规则（LLM 不可用时） ===
def fallback_strategy_decision(ctx: NegotiationContext) -> str:
    """LLM 不可用时，降级到 V1.2 规则选策略 id。"""
    from .negotiation import choose_strategy
    strategy = choose_strategy(ctx)
    if strategy:
        return strategy.id
    return "walk_away"


def fallback_outcome_assessment(merchant_text: str, original_price_pct: float, original_price_abs: float) -> dict:
    """LLM 不可用时，简单的关键词判断。"""
    text = merchant_text.lower()
    # 商家让步关键词
    success_kw = ["discount", "alternative", "consider", "reduce", "compromise", "available",
                 "お値引き", "割引", "代替", "検討", "大丈夫", "可能です", "ご利用いただけます",
                 "할인", "대안", "검토", "가능", "있습니다"]
    # 商家拒绝关键词
    fail_kw = ["can't", "cannot", "unable", "no way", "impossible", "not possible",
               "無理", "できない", "申し訳ございません",
               "불가능", "죄송합니다", "안 됩니다"]

    if any(kw.lower() in text for kw in success_kw):
        new_pct = max(0, original_price_pct * 0.5)
        new_abs = max(0, original_price_abs * 0.5)
        return {"outcome": "success", "new_price_pct": new_pct, "new_price_abs": new_abs, "reason": "fallback: 命中成功关键词"}
    if any(kw.lower() in text for kw in fail_kw):
        return {"outcome": "failed", "new_price_pct": original_price_pct, "new_price_abs": original_price_abs, "reason": "fallback: 命中失败关键词"}
    return {"outcome": "neutral", "new_price_pct": original_price_pct, "new_price_abs": original_price_abs, "reason": "fallback: 无明确信号"}


# === V2.0 完整决策（优先 LLM，降级规则） ===
async def decide_next_move(
    full_dialogue: list[dict],
    ctx: NegotiationContext,
    user_requirement: str,
    user_constraints: str | None,
    lang: str,
    organization: str,
) -> tuple[str, str, str]:
    """决策下一步。返回 (strategy_id, ai_speech, reasoning)。

    优先 LLM；不可用降级到 V1.2 规则。
    """
    # 1. 试 LLM
    llm_decision = await call_llm_for_negotiation(
        full_dialogue, ctx, user_requirement, user_constraints, lang, organization
    )

    if llm_decision:
        return (
            llm_decision.get("strategy_id", "hold_position"),
            llm_decision.get("ai_speech", ""),
            f"LLM: {llm_decision.get('reasoning', '')}",
        )

    # 2. 降级到 V1.2 规则
    strategy_id = fallback_strategy_decision(ctx)
    strategy = STRATEGY_BY_ID.get(strategy_id)
    if strategy is None:
        strategy = STRATEGY_WALK_AWAY
        strategy_id = "walk_away"

    # 用 V1.2 模板 + 上下文变量
    vars = {
        "original_date": "6.12",
        "alt_dates": "6.13 or 6.14",
        "price": f"¥{ctx.price_change_abs:.0f}" if ctx.price_change_abs else "未知",
        "value_added": _scenario_value_added(ctx.scenario, lang),
        "bundle_items": ", ".join(["extra services"]),
        "company": organization,
        "stays": "3-4",
        "budget": f"¥{int(ctx.price_change_abs * 3):.0f}" if ctx.price_change_abs else "fixed",
        "constraint": user_constraints or "预算",
    }
    tmpl = strategy.templates.get(lang, strategy.templates.get("en", ""))
    ai_speech = tmpl.format(**vars) if "{" in tmpl else tmpl
    return (strategy_id, ai_speech, f"V1.2 规则降级: {strategy_id}")


async def assess_outcome(
    strategy_id: str,
    ai_speech: str,
    merchant_text: str,
    original_price_pct: float,
    original_price_abs: float,
    lang: str,
) -> dict:
    """评估商家回复。优先 LLM；降级 V1.2 关键词。"""
    llm_result = await call_llm_for_outcome_assessment(
        strategy_id, ai_speech, merchant_text, original_price_pct, original_price_abs, lang
    )
    if llm_result:
        return llm_result
    return fallback_outcome_assessment(merchant_text, original_price_pct, original_price_abs)


def _scenario_value_added(scenario: str, lang: str) -> str:
    return {
        "hotel": {"ja": "朝食2泊分", "ko": "조식 2박분", "en": "2-night breakfast package"},
        "car_rental": {"ja": "フル保険", "ko": "풀 보험", "en": "full insurance coverage"},
        "flight": {"ja": "機内食と追加手荷物", "ko": "기내식과 추가 수하물", "en": "premium meal + extra baggage"},
    }.get(scenario, {"ja": "追加サービス", "ko": "추가 서비스", "en": "additional services"}).get(lang, "additional services")

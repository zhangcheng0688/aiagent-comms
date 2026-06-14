"""V2.0 真 LLM 决策端到端：让 MiniMax-M3 真正选择策略 + 评估商家。

3 个场景 × 2 轮 = 6 次 LLM 决策调用 + 3 次 outcome 评估调用。
结果会同时打印 LLM 的 strategy_id 和 reasoning，与 V1.2 fallback 对比。
"""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.storage import storage
from backend.models import Order, OrderState, OrderStatus, Channel
from backend.core.dialogue import DialogueEngine
from backend.channels.voice import VoiceChannel
from backend.channels.sms import SmsChannel
from backend.core.intent_parser import parse_intent
from backend.core.llm_negotiator import (
    decide_next_move, assess_outcome,
    call_llm_for_negotiation, call_llm_for_outcome_assessment,
)
from backend.core.negotiation import NegotiationContext


async def case_one(scenario_name, organization, contact, requirement, constraints, channel, lang):
    """跑单个 case，全程打印 LLM 决策细节。"""
    print(f"\n{'='*70}")
    print(f"🧪 场景: {scenario_name}  商家: {organization}")
    print(f"{'='*70}")

    intents = await parse_intent(requirement, constraints, scenario_name)
    order = Order(
        id=f"ord_real_{uuid.uuid4().hex[:6]}",
        organization=organization,
        contact_number=contact,
        requirement=requirement,
        constraints=constraints,
        target_language=lang,
        preferred_channel=channel,
        scenario=scenario_name,
        state=OrderState.INIT,
        status=OrderStatus.PENDING,
        intents=intents,
        dialogue=[],
        result=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await storage.create_order(order)
    order.status = OrderStatus.IN_PROGRESS

    voice = VoiceChannel(mock=True)
    sms = SmsChannel(mock=True)
    engine = DialogueEngine(voice=voice, sms=sms)

    try:
        updated = await engine.run(order)
        await storage.update_order(updated)
    except Exception as e:
        print(f"  ❌ 异常: {e}")
        return

    print(f"\n  📋 需求: {requirement}")
    print(f"  📋 约束: {constraints or '（无）'}")
    print(f"  📋 状态: {updated.status.value}")
    print(f"  📋 轮数: {len(updated.dialogue)//2}")

    llm_driven = (updated.result or {}).get('receipt', {}).get('llm_driven', False)
    print(f"  📋 LLM_driven: {llm_driven}")

    tried = (updated.result or {}).get('tried_strategies', [])
    print(f"  📋 已用策略: {tried}")

    if updated.status == OrderStatus.NEEDS_USER:
        reason = (updated.result or {}).get('reason', '')
        print(f"  📋 升级: {reason}")

    # 打印完整对话
    print(f"\n  --- 对话回放 ---")
    for turn in updated.dialogue:
        speaker = "🤖 AI" if turn.speaker == "ai" else "🏨 商家"
        body = turn.translated if turn.speaker == "merchant" else turn.original
        print(f"  {speaker}: {body}")
        if turn.speaker == "merchant" and turn.original != turn.translated:
            print(f"        (原: {turn.original})")


async def main():
    # 关键：使用真 MAVIS_ACCESS_TOKEN
    print("🔑 鉴权: MAVIS_ACCESS_TOKEN 走 Mavis daemon 的 LLM endpoint")
    print("🔗 endpoint: https://agent.minimaxi.com/mavis/api/v1/llm/v1/messages")
    print(f"🔗 model: MiniMax-M3\n")

    db_path = Path("/Users/chenwanyi/Documents/mini Max/aiagent-comms/data/orders.db")
    if db_path.exists():
        db_path.unlink()
    await storage.init()

    cases = [
        # Case 1: 酒店 - 用户硬约束"不可加价"，商家加价 → LLM 应优先 hold_position
        ("hotel", "大阪心斋桥大和鲁内酒店", "+81661234567",
         "帮我致电酒店改入住 6.12 双床+免费早餐", "不可加价", Channel.VOICE, "ja"),

        # Case 2: 租车 - 英语 - 无约束，商家加价 → LLM 应决策 chain_offer
        ("car_rental", "Hertz Honolulu", "+18084373000",
         "I need an economy car for 3 days at the airport.",
         None, Channel.SMS, "en"),

        # Case 3: 机票 - 旺季改签，大幅加价 → LLM 应决策 escalate 或 walk_away
        ("flight", "ANA Customer Service", "+18184674000",
         "Please change my flight to June 15, peak season upgrade.",
         None, Channel.VOICE, "en"),
    ]

    for c in cases:
        await case_one(*c)


if __name__ == "__main__":
    asyncio.run(main())

"""V1.2 端到端测试：3 场景 × 3 复杂协商用例。"""
import asyncio
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

os.environ["LLM_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.storage import storage
from backend.models import Order, OrderState, OrderStatus, Channel
from backend.core.dialogue import DialogueEngine
from backend.channels.voice import VoiceChannel
from backend.channels.sms import SmsChannel
from backend.core.intent_parser import parse_intent


async def main():
    print("=" * 70)
    print("AI 全权代办沟通 V1.2 — 复杂协商端到端测试")
    print("=" * 70)
    await storage.init()

    test_cases = [
        # === 酒店 ===
        {"scenario": "hotel", "name": "酒店·日语·用户硬约束不可加价 + 商家升级 (AI 应主动 hold + chain + walkaway)",
         "organization": "大阪心斋桥大和鲁内酒店", "contact_number": "+81661234567",
         "requirement": "帮我致电酒店改入住 6.12 双床+免费早餐", "constraints": "不可加价",
         "channel": Channel.VOICE, "lang": "ja", "expect": "walkaway_or_escalated"},
        {"scenario": "hotel", "name": "酒店·英语·AI 增值让步换不加价",
         "organization": "Hilton Tokyo", "contact_number": "+81312341234",
         "requirement": "Please upgrade my room to a deluxe, but stay under original budget.",
         "constraints": None, "channel": Channel.VOICE, "lang": "en", "expect": "value_trade_success"},
        {"scenario": "hotel", "name": "酒店·韩语·alt_date 替代日期成功",
         "organization": "롯데호텔 서울", "contact_number": "+8227711000",
         "requirement": "6월 13일로 예약 변경 부탁드립니다.", "constraints": None,
         "channel": Channel.SMS, "lang": "ko", "expect": "alt_date_success"},

        # === 租车 ===
        {"scenario": "car_rental", "name": "租车·日语·用户不可加价 + AI 应 chain_offer",
         "organization": "トヨタレンタカー 関西空港", "contact_number": "+81755678901",
         "requirement": "经济型 6.12-6.15 机场取还 含全险", "constraints": "不可加价",
         "channel": Channel.VOICE, "lang": "ja", "expect": "chain_offer_attempt"},
        {"scenario": "car_rental", "name": "租车·英语·AI 忠诚度换价",
         "organization": "Hertz Honolulu", "contact_number": "+18084373000",
         "requirement": "I need an economy car for 3 days at the airport.",
         "constraints": None, "channel": Channel.SMS, "lang": "en", "expect": "loyalty_attempt"},
        {"scenario": "car_rental", "name": "租车·韩语·AI 增值让步",
         "organization": "롯데렌터카 부산", "contact_number": "+8251123456",
         "requirement": "부산역에서 SUV 3일 렌트, 풀보험 포함",
         "constraints": None, "channel": Channel.SMS, "lang": "ko", "expect": "value_trade"},

        # === 机票 ===
        {"scenario": "flight", "name": "机票·日语·改签旺季 (AI 应 hold → chain → escalate)",
         "organization": "JAL お客様センター", "contact_number": "+81312321321",
         "requirement": "予約を 6月15日に変更し、プレミアムエコノミーにアップグレードしたい。",
         "constraints": None, "channel": Channel.VOICE, "lang": "ja", "expect": "escalated"},
        {"scenario": "flight", "name": "机票·英语·退款 + AI 灵活处理",
         "organization": "Delta Customer Service", "contact_number": "+18005552553",
         "requirement": "I need to cancel my flight and get a refund.",
         "constraints": "希望全额退款", "channel": Channel.VOICE, "lang": "en", "expect": "refund_processed"},
        {"scenario": "flight", "name": "机票·韩语·选座 + 餐食简单对话",
         "organization": "대한항공 고객센터", "contact_number": "+82215881600",
         "requirement": "좌석 선택과 기내식 주문 부탁드립니다. 창가 좌석으로.",
         "constraints": None, "channel": Channel.SMS, "lang": "ko", "expect": "simple_success"},
    ]

    voice = VoiceChannel(mock=True)
    sms = SmsChannel(mock=True)
    engine = DialogueEngine(voice=voice, sms=sms)

    results = []

    for tc in test_cases:
        print(f"\n{'='*70}")
        print(f"📋 {tc['name']} [{tc['scenario']}]")
        print(f"   需求: {tc['requirement'][:60]}{'...' if len(tc['requirement'])>60 else ''}")
        print(f"   约束: {tc['constraints'] or '无'}")
        print("=" * 70)

        intents = await parse_intent(tc["requirement"], tc["constraints"], tc["scenario"])
        print(f"\n[拆解] {len(intents)} 项:")
        for i in intents:
            print(f"   - [{i.type}] {i.description} → {i.target_value}")

        order = Order(
            id=f"ord_v12_{uuid.uuid4().hex[:8]}",
            organization=tc["organization"],
            contact_number=tc["contact_number"],
            requirement=tc["requirement"],
            constraints=tc["constraints"],
            target_language=tc["lang"],
            preferred_channel=tc["channel"],
            scenario=tc["scenario"],
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

        try:
            updated = await engine.run(order)
            await storage.update_order(updated)
        except Exception as e:
            print(f"   ❌ 异常: {e}")
            import traceback; traceback.print_exc()
            results.append((tc["name"], "error", str(e)))
            continue

        # 报告
        print(f"\n[结果] state={updated.state.value} status={updated.status.value}")
        print(f"   对话轮数: {len(updated.dialogue)//2}")
        print(f"   确认诉求: {sum(1 for i in updated.intents if i.confirmed_value)}/{len(updated.intents)}")
        if updated.result and updated.result.get("negotiation_required"):
            tried = updated.result.get('tried_strategies', [])
            print(f"   协商策略已用: {tried}")
            print(f"   升级原因: {updated.result.get('reason')}")
        if updated.result and "summary" in updated.result:
            print(f"   总结: {updated.result.get('summary')}")

        # 显示对话片段
        print(f"\n[对话] (前 6 轮):")
        for turn in updated.dialogue[:12]:
            tag = "🤖" if turn.speaker == "ai" else "👔"
            content = turn.translated[:80] + ("..." if len(turn.translated) > 80 else "")
            print(f"   {tag} {content}")

        results.append((tc["name"], updated.status.value, updated.state.value))

    print(f"\n{'='*70}")
    print("📊 V1.2 复杂协商测试汇总")
    print(f"{'='*70}")
    for name, status, state in results:
        print(f"  [{status:8s}] {state:18s} - {name}")
    success_count = sum(1 for _, s, _ in results if s == "success")
    need_count = sum(1 for _, s, _ in results if s == "needs_user")
    fail_count = sum(1 for _, s, _ in results if s == "failed")
    print(f"\n  ✅ 成功: {success_count}  ⚠️ 升级等决策: {need_count}  ❌ 失败: {fail_count}  / 总: {len(results)}")


if __name__ == "__main__":
    asyncio.run(main())

"""V1.1 端到端测试：3 个场景 × 3 个语种 = 9 个测试用例。"""
import asyncio
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

os.environ["LLM_API_KEY"] = ""  # 强制走离线规则

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.storage import storage
from backend.models import Order, OrderState, OrderStatus, IntentSlot, Channel
from backend.core.dialogue import DialogueEngine
from backend.channels.voice import VoiceChannel
from backend.channels.sms import SmsChannel
from backend.core.intent_parser import parse_intent, detect_scenario


async def main():
    print("=" * 70)
    print("AI 全权代办沟通 V1.1 — 端到端测试（hotel/car_rental/flight × ja/ko/en）")
    print("=" * 70)

    await storage.init()

    test_cases = [
        {"scenario": "hotel", "name": "酒店·日语·改期",
         "organization": "大阪心斋桥大和鲁内酒店", "contact_number": "+81661234567",
         "requirement": "帮我致电酒店改入住 6.12，确认双床和免费早餐",
         "constraints": "不可加价", "channel": Channel.SMS, "lang": "ja"},
        {"scenario": "hotel", "name": "酒店·韩语·取消",
         "organization": "首尔明洞乐天酒店", "contact_number": "+82223456789",
         "requirement": "帮我取消这个预订，理由是行程冲突",
         "constraints": "希望免费取消", "channel": Channel.SMS, "lang": "ko"},
        {"scenario": "car_rental", "name": "租车·日语·保险+IDP",
         "organization": "丰田租车 关西机场店", "contact_number": "+81755678901",
         "requirement": "我想租一辆经济型车，6.12 取车 6.15 还车，机场取还，含全险 + 不限里程。请问中国驾照加国际驾照翻译件能用吗？",
         "constraints": None, "channel": Channel.VOICE, "lang": "ja"},
        {"scenario": "car_rental", "name": "租车·韩语·异地还车",
         "organization": "롯데렌터카 서울역", "contact_number": "+8227712345",
         "requirement": "서울역에서 빌려서 부산에서 반납하고 싶어요. 가격 확인 부탁해요.",
         "constraints": None, "channel": Channel.SMS, "lang": "ko"},
        {"scenario": "flight", "name": "机票·英语·改签旺季",
         "organization": "ANA Customer Service", "contact_number": "+18184674000",
         "requirement": "Please change my flight to June 15, and upgrade to business class.",
         "constraints": None, "channel": Channel.VOICE, "lang": "en"},
        {"scenario": "flight", "name": "机票·日语·退票",
         "organization": "JAL お客様センター", "contact_number": "+81312321321",
         "requirement": "予約の払い戻しをお願いします。",
         "constraints": None, "channel": Channel.SMS, "lang": "ja"},
    ]

    voice = VoiceChannel(mock=True)
    sms = SmsChannel(mock=True)
    engine = DialogueEngine(voice=voice, sms=sms)

    summary = {"success": [], "needs_user": [], "failed": []}

    for tc in test_cases:
        print(f"\n{'='*70}")
        print(f"📋 {tc['name']} [{tc['scenario']}]")
        print(f"   机构: {tc['organization']} ({tc['contact_number']})")
        print(f"   需求: {tc['requirement'][:60]}{'...' if len(tc['requirement'])>60 else ''}")
        print("=" * 70)

        # 1) 拆解
        intents = await parse_intent(tc["requirement"], tc["constraints"], tc["scenario"])
        print(f"\n[1] 拆解 ({len(intents)} 项):")
        for i in intents:
            print(f"   - [{i.type}] {i.description} → {i.target_value}")

        # 2) 创建订单
        order = Order(
            id=f"ord_v11_{uuid.uuid4().hex[:8]}",
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

        # 3) 跑引擎
        try:
            updated = await engine.run(order)
            await storage.update_order(updated)
        except Exception as e:
            print(f"   ❌ 异常: {e}")
            summary["failed"].append((tc["name"], str(e)))
            continue

        # 4) 报告
        print(f"\n[2] 结果: state={updated.state.value} status={updated.status.value}")
        print(f"   场景: {updated.scenario} | 语种: {updated.target_language} | 通道: {updated.preferred_channel.value}")
        print(f"   对话轮数: {len(updated.dialogue)//2}")
        print(f"   确认诉求: {sum(1 for i in updated.intents if i.confirmed_value)}/{len(updated.intents)}")
        if updated.result and updated.result.get("negotiation_required"):
            print(f"   ⚠️  触发升级: {updated.result.get('reason')}")

        if updated.status == OrderStatus.SUCCESS:
            summary["success"].append(tc["name"])
        elif updated.status == OrderStatus.NEEDS_USER:
            summary["needs_user"].append(tc["name"])
        else:
            summary["failed"].append(tc["name"], f"状态 {updated.status}")

    print(f"\n{'='*70}")
    print("📊 V1.1 测试结果汇总")
    print(f"   ✅ 成功: {len(summary['success'])}/{len(test_cases)}")
    for n in summary["success"]:
        print(f"      - {n}")
    print(f"   ⚠️  升级等决策: {len(summary['needs_user'])}/{len(test_cases)}")
    for n in summary["needs_user"]:
        print(f"      - {n}")
    print(f"   ❌ 失败: {len(summary['failed'])}/{len(test_cases)}")
    for n in summary["failed"]:
        print(f"      - {n}")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())

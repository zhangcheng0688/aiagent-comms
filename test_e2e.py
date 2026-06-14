"""端到端集成测试：不依赖 LLM，跑通核心流程。"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# 强制无 LLM 模式
import os
os.environ["LLM_API_KEY"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.storage import storage
from backend.models import Order, OrderState, OrderStatus, IntentSlot, Channel
from backend.core.dialogue import DialogueEngine
from backend.channels.voice import VoiceChannel
from backend.channels.sms import SmsChannel
from backend.core.intent_parser import parse_intent, _offline_parse


async def main():
    print("=" * 70)
    print("AI 全权代办沟通 V1.0 — 端到端测试")
    print("=" * 70)

    # 初始化 storage
    await storage.init()

    # 测试用例
    test_cases = [
        {
            "name": "场景 1：改期 + 双床 + 早餐（无升级，happy path）",
            "organization": "大阪心斋桥大和鲁内酒店",
            "contact_number": "+81661234567",
            "requirement": "帮我致电酒店改入住 6.12，确认双床和免费早餐",
            "constraints": "不可加价",
            "preferred_channel": Channel.SMS,
        },
        {
            "name": "场景 2：改期触发升级（升级到豪华房加价）",
            "organization": "京都清水寺旅馆",
            "contact_number": "+81755678901",
            "requirement": "请帮我把预订改到 6.12 双床+早餐",
            "constraints": None,
            "preferred_channel": Channel.VOICE,
        },
        {
            "name": "场景 3：取消预订（简单对话）",
            "organization": "首尔明洞乐天酒店",
            "contact_number": "+82223456789",
            "requirement": "帮我取消这个预订，理由是行程冲突",
            "constraints": "希望免费取消",
            "preferred_channel": Channel.SMS,
        },
    ]

    voice = VoiceChannel(mock=True)
    sms = SmsChannel(mock=True)
    engine = DialogueEngine(voice=voice, sms=sms)

    for tc in test_cases:
        print(f"\n{'='*70}")
        print(f"📋 {tc['name']}")
        print(f"   目标: {tc['organization']} ({tc['contact_number']})")
        print(f"   需求: {tc['requirement']}")
        print(f"   通道: {tc['preferred_channel'].value} | 约束: {tc['constraints']}")
        print("=" * 70)

        # 1) 拆解意图
        print("\n[1] 拆解意图...")
        intents = await parse_intent(tc["requirement"], tc["constraints"])
        for i in intents:
            print(f"   - [{i.type}] {i.description} (target: {i.target_value})")

        # 2) 创建订单
        import uuid as _uuid
        order = Order(
            id=f"ord_test_{_uuid.uuid4().hex[:10]}",
            organization=tc["organization"],
            contact_number=tc["contact_number"],
            requirement=tc["requirement"],
            constraints=tc["constraints"],
            target_language="ja" if tc["contact_number"].startswith("+81") else ("ko" if tc["contact_number"].startswith("+82") else "en"),
            preferred_channel=tc["preferred_channel"],
            state=OrderState.INIT,
            status=OrderStatus.PENDING,
            intents=intents,
            dialogue=[],
            result=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        await storage.create_order(order)
        print(f"\n[2] 订单创建: {order.id}")
        print(f"   目标语种: {order.target_language}")

        # 3) 跑对话引擎
        print(f"\n[3] 跑对话引擎...")
        order.status = OrderStatus.IN_PROGRESS
        updated = await engine.run(order)
        await storage.update_order(updated)

        # 4) 打印结果
        print(f"\n[4] 最终状态: {updated.state.value} / {updated.status.value}")
        print(f"   对话轮数: {len(updated.dialogue) // 2}")
        print(f"   确认诉求数: {sum(1 for i in updated.intents if i.confirmed_value)}")
        if updated.result:
            print(f"   结果摘要: {updated.result.get('summary', '')}")
            if updated.result.get("negotiation_required"):
                print(f"   ⚠️  触发升级: {updated.result.get('reason')}")
                print(f"   备选方案: {[o.get('label') for o in updated.result.get('proposal', {}).get('options', [])]}")

        # 5) 打印双语对话
        print(f"\n[5] 对话记录:")
        for t in updated.dialogue:
            tag = "🤖" if t.speaker == "ai" else "👔"
            print(f"   {tag} [{t.speaker.upper()}]")
            print(f"      中文: {t.translated}")
            if t.speaker == "merchant" and t.original != t.translated:
                print(f"      原话: {t.original}")

        # 场景 2 模拟用户决策
        if updated.status == OrderStatus.NEEDS_USER:
            print(f"\n[6] 模拟用户决策：选 A")
            from backend.main import _run_order_in_background  # noqa
            # 模拟用户选 A
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"http://127.0.0.1:8765/api/orders/{updated.id}/resolve-proposal",
                    json={"choice": "A"},
                )
                print(f"   决策 API 响应: {resp.status_code}")

    print(f"\n{'='*70}")
    print("✅ 全部测试场景跑完")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())

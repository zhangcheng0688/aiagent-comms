"""V2.0 端到端测试：3 模式 × 3 场景 = 9 个用例。

3 模式：
- LLM 模式：MOCK_LLM=1，用预定义 mock LLM 决策
- 降级模式：MOCK_LLM=0 + 无 API key，强制走 V1.2 规则
- 真实 LLM 模式（用户填 LLM_API_KEY 后）

每模式各跑：酒店/租车/机票 各 1 复杂协商用例。
"""
import asyncio
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


async def run_mode(mode_name: str, mock_llm: bool, has_key: bool):
    print(f"\n{'='*70}")
    print(f"🧪 模式: {mode_name}（MOCK_LLM={mock_llm}, has_key={has_key}）")
    print(f"{'='*70}")

    if mock_llm:
        os.environ["MOCK_LLM"] = "1"
    else:
        os.environ["MOCK_LLM"] = "0"

    if has_key:
        os.environ["LLM_API_KEY"] = "sk-fake-test-key"  # 让 call_llm 真的尝试调用（会失败但走完链路）
    else:
        os.environ["LLM_API_KEY"] = ""

    # 重新 import 拿到新配置
    import importlib
    import backend.core.llm_negotiator
    importlib.reload(backend.core.llm_negotiator)

    # 重置 SQLite
    db_path = Path("/Users/chenwanyi/Documents/mini Max/aiagent-comms/data/orders.db")
    if db_path.exists():
        db_path.unlink()

    await storage.init()

    test_cases = [
        {"scenario": "hotel", "name": "酒店·用户硬约束 + 商家升级",
         "organization": "大阪心斋桥大和鲁内酒店", "contact_number": "+81661234567",
         "requirement": "帮我致电酒店改入住 6.12 双床+免费早餐", "constraints": "不可加价",
         "channel": Channel.VOICE, "lang": "ja"},
        {"scenario": "car_rental", "name": "租车·英语·无约束 + 商家加价",
         "organization": "Hertz Honolulu", "contact_number": "+18084373000",
         "requirement": "I need an economy car for 3 days at the airport.",
         "constraints": None, "channel": Channel.SMS, "lang": "en"},
        {"scenario": "flight", "name": "机票·改签旺季 + 大幅加价",
         "organization": "ANA Customer Service", "contact_number": "+18184674000",
         "requirement": "Please change my flight to June 15, peak season upgrade.",
         "constraints": None, "channel": Channel.VOICE, "lang": "en"},
    ]

    voice = VoiceChannel(mock=True)
    sms = SmsChannel(mock=True)
    engine = DialogueEngine(voice=voice, sms=sms)

    results = []
    for tc in test_cases:
        print(f"\n  📋 {tc['name']} [{tc['scenario']}]")

        intents = await parse_intent(tc["requirement"], tc["constraints"], tc["scenario"])
        order = Order(
            id=f"ord_v20_{uuid.uuid4().hex[:6]}",
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
            print(f"     ❌ 异常: {e}")
            results.append((tc["name"], "error", ""))
            continue

        tried = (updated.result or {}).get('tried_strategies', [])
        reason = (updated.result or {}).get('reason', '') if updated.status == OrderStatus.NEEDS_USER else ''
        llm_driven = (updated.result or {}).get('receipt', {}).get('llm_driven', False)
        rounds = len(updated.dialogue) // 2

        print(f"     状态: {updated.status.value} | 对话轮: {rounds} | 策略: {tried}")
        if updated.status == OrderStatus.NEEDS_USER:
            print(f"     升级: {reason}")
        results.append((tc["name"], updated.status.value, tried))

    print(f"\n  {mode_name} 汇总:")
    success = sum(1 for _, s, _ in results if s == "success")
    need = sum(1 for _, s, _ in results if s == "needs_user")
    fail = sum(1 for _, s, _ in results if s == "failed")
    print(f"     ✅ {success}  ⚠️ {need}  ❌ {fail}  / 总 {len(results)}")
    return results


async def main():
    print("=" * 70)
    print("AI 全权代办沟通 V2.0 — 复杂协商（LLM 驱动策略选择）")
    print("=" * 70)

    all_results = {}

    # 1. Mock LLM 模式
    all_results["mock_llm"] = await run_mode("Mock LLM 模式", mock_llm=True, has_key=False)

    # 2. 降级模式（无 API key）
    all_results["degraded"] = await run_mode("V1.2 降级模式（无 LLM key）", mock_llm=False, has_key=False)

    # 3. 真实 LLM 调用（key 假，会失败但走完整降级）
    all_results["real_llm_attempt"] = await run_mode("真实 LLM 调用（key 假，会降级）", mock_llm=False, has_key=True)

    print(f"\n{'='*70}")
    print("📊 V2.0 三模式总览")
    print(f"{'='*70}")
    for mode, results in all_results.items():
        success = sum(1 for _, s, _ in results if s == "success")
        need = sum(1 for _, s, _ in results if s == "needs_user")
        fail = sum(1 for _, s, _ in results if s == "failed")
        print(f"  {mode:30s}  ✅ {success}  ⚠️ {need}  ❌ {fail}  / 总 {len(results)}")


if __name__ == "__main__":
    asyncio.run(main())

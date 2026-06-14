"""V2.1 真机测试：3 场景跑完 + 自动评估。"""
import asyncio
import os
import sys
import uuid
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.storage import storage
from backend.models import Order, OrderState, OrderStatus, Channel
from backend.core.dialogue import DialogueEngine
from backend.channels.voice import VoiceChannel
from backend.channels.sms import SmsChannel
from backend.core.intent_parser import parse_intent
from backend.core.evaluator import evaluate_order, score_to_dict


CASES = [
    {"scenario": "hotel", "name": "酒店", "organization": "大阪心斋桥大和鲁内酒店",
     "contact": "+81661234567", "requirement": "帮我致电酒店改入住 6.12 双床+免费早餐",
     "constraints": "不可加价", "channel": Channel.VOICE, "lang": "ja"},
    {"scenario": "car_rental", "name": "租车", "organization": "Hertz Honolulu",
     "contact": "+18084373000", "requirement": "I need an economy car for 3 days at the airport.",
     "constraints": None, "channel": Channel.SMS, "lang": "en"},
    {"scenario": "flight", "name": "机票", "organization": "ANA Customer Service",
     "contact": "+18184674000", "requirement": "Please change my flight to June 15, peak season upgrade.",
     "constraints": None, "channel": Channel.VOICE, "lang": "en"},
]


async def run_one(c):
    intents = await parse_intent(c["requirement"], c["constraints"], c["scenario"])
    order = Order(
        id=f"ord_v21_{uuid.uuid4().hex[:6]}",
        organization=c["organization"],
        contact_number=c["contact"],
        requirement=c["requirement"],
        constraints=c["constraints"],
        target_language=c["lang"],
        preferred_channel=c["channel"],
        scenario=c["scenario"],
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
        print(f"  ❌ {c['name']}: {e}")
        return None
    return updated


async def main():
    print("=" * 70)
    print("V2.1 AI 表现评估 · 真 MiniMax-M3 端到端")
    print("=" * 70)

    db = Path("/Users/chenwanyi/Documents/mini Max/aiagent-comms/data/orders.db")
    if db.exists():
        db.unlink()
    await storage.init()

    results = []
    for c in CASES:
        print(f"\n▶ {c['name']} ...")
        order = await run_one(c)
        if not order:
            continue
        print(f"  状态: {order.status.value} | 轮数: {len(order.dialogue)//2}")
        results.append((c, order))

    # 评估
    print(f"\n{'='*70}")
    print(f"📊 V2.1 评估结果")
    print(f"{'='*70}")
    eval_results = []
    for c, order in results:
        score = await evaluate_order(order)
        d = score_to_dict(score)
        eval_results.append((c, order, d))
        print(f"\n  {c['name']}:")
        print(f"    总分: {d['total']} / 100  ({d['engine']})")
        for k, v in d['dimensions'].items():
            print(f"      {v['label']:<6} {v['score']:>2}/{v['max']}")
        if d['suggestions']:
            print(f"    建议:")
            for s in d['suggestions'][:3]:
                print(f"      • {s}")

    # 写 JSON
    out = Path("/Users/chenwanyi/Documents/mini Max/aiagent-comms/docs/report/v21_eval_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump([
            {
                "scenario": c["scenario"],
                "name": c["name"],
                "order_id": o.id,
                "status": o.status.value,
                "rounds": len(o.dialogue) // 2,
                "evaluation": d,
            }
            for c, o, d in eval_results
        ], f, ensure_ascii=False, indent=2)
    print(f"\n✅ 评估结果已写入: {out}")


if __name__ == "__main__":
    asyncio.run(main())

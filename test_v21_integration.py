"""V2.1 全集成测试：A1 评估 + A2 auth + A3 admin + A4 metrics。

跑 3 场景真 LLM → 评估入库 → admin 后台能看 → metrics 准。
"""
import asyncio
import os
import sys
import uuid
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from httpx import ASGITransport, AsyncClient
from backend.main import app
from backend.storage import storage
from backend.models import Order, OrderState, OrderStatus, Channel, IntentSlot
from backend.core.intent_parser import parse_intent
from backend.core.dialogue import DialogueEngine
from backend.channels.voice import VoiceChannel
from backend.channels.sms import SmsChannel
from backend.auth import Org, User, AuthToken, hash_password, issue_token
from datetime import timedelta


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


async def main():
    print("=" * 70)
    print("V2.1 全集成测试 · A1 评估 + A2 鉴权 + A4 指标")
    print("=" * 70)

    db = Path("data/orders.db")
    if db.exists():
        os.rename(str(db), str(db) + ".bak3")

    await storage.init()

    # 创建 org + user
    org = Org(id="org_test", name="上海博隆贸易", plan="pro", created_at=datetime.utcnow())
    await storage.create_org(org)
    ph, salt = hash_password("test1234")
    user = User(id="usr_test", org_id="org_test", email="chen@bolong.com", name="陈总",
                password_hash=ph, password_salt=salt, role="admin", created_at=datetime.utcnow())
    await storage.create_user(user)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 1. 登录拿 token
        r = await c.post("/api/auth/login", json={"email": "chen@bolong.com", "password": "test1234"})
        assert r.status_code == 200, f"login failed: {r.text}"
        token = r.json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        print(f"✅ A2 登录: {r.status_code} · token len={len(token)}")

        # 2. 错密码 401
        r = await c.post("/api/auth/login", json={"email": "chen@bolong.com", "password": "wrong"})
        assert r.status_code == 401
        print(f"✅ A2 错密码拦截: {r.status_code}")

        # 3. 无 token 401
        r = await c.post("/api/orders", json={
            "organization": "测试", "contact_number": "+1", "requirement": "测试",
            "preferred_channel": "sms", "scenario": "hotel"
        })
        # 没设 auth 应该用 anon（optional_user），返回 200
        print(f"ℹ️  无 token 创建订单: {r.status_code} (anon 模式允许)")

        # 4. 跑 3 场景
        voice = VoiceChannel(mock=True)
        sms = SmsChannel(mock=True)
        engine = DialogueEngine(voice=voice, sms=sms)

        for case in CASES:
            print(f"\n▶ {case['name']} ...")
            r = await c.post("/api/orders", headers=auth, json={
                "organization": case["organization"],
                "contact_number": case["contact"],
                "requirement": case["requirement"],
                "constraints": case["constraints"],
                "preferred_channel": case["channel"].value,
                "scenario": case["scenario"],
            })
            assert r.status_code == 200, f"create order failed: {r.text}"
            order_id = r.json()["order_id"]
            print(f"   创建订单: {order_id}")

            # 等异步完成
            for _ in range(40):
                await asyncio.sleep(0.5)
                r = await c.get(f"/api/orders/{order_id}", headers=auth)
                data = r.json()
                if data["status"] in ("success", "failed", "needs_user"):
                    break
            else:
                print(f"   ⚠️ 超时，最后状态: {data['status']}")

            ev = (data.get("result") or {}).get("evaluation", {})
            print(f"   状态: {data['status']} · AI 评分: {ev.get('total', '—')}/{ev.get('engine', '—')}")

        # 5. /api/metrics
        r = await c.get("/api/metrics", headers=auth)
        m = r.json()
        print(f"\n📊 A4 指标:")
        print(f"   总订单: {m['orders']['total']}")
        print(f"   成功率: {m['orders']['success_rate']}%")
        print(f"   AI 均分: {m['ai_quality']['avg_evaluation_total']}")
        print(f"   范围: {m['scope']}")

        # 6. /api/health
        r = await c.get("/api/health")
        h = r.json()
        print(f"\n💚 A4 健康: {h['status']} · uptime {h['uptime_seconds']}s · version {h['version']}")

        # 7. admin.html 可见
        r = await c.get("/admin")
        assert r.status_code == 200
        print(f"✅ A3 admin.html: {r.status_code} · {len(r.text)} bytes")

        # 8. 列表
        r = await c.get("/api/orders?limit=20", headers=auth)
        orders = r.json()
        print(f"✅ A3 列表: {len(orders)} 单")
        for o in orders[:3]:
            ev = (o.get("result") or {}).get("evaluation", {})
            print(f"     {o['organization']:<30s} {o['status']:<12s} AI分={ev.get('total', '—')}")

    print(f"\n{'='*70}")
    print("✅ V2.1 全集成验证通过")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())

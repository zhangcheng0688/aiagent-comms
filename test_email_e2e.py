"""C3/C4 联调：构造邮件 → 解析 → 调后端 API → 生成回复。

不依赖真实 IMAP。直接调 EmailParser + BackendClient + build_reply。
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.email_worker import (
    EmailParser, BackendClient, build_reply, ParsedOrder,
)


SAMPLE_HOTEL = (
    'From: "李总" <li@example.com>\n'
    'To: aiagent@qq.com\n'
    'Subject: 帮我订三亚海棠湾威斯汀\n'
    'Message-ID: <e2e001@example.com>\n'
    'Date: Mon, 10 Feb 2025 10:00:00 +0800\n'
    'Content-Type: text/plain; charset=utf-8\n'
    '\n'
    'AI 你好，下周三（3/19）我带家人去三亚玩 3 晚，'
    '帮我订海棠湾威斯汀度假酒店，'
    '电话 +86-898-88658888，1 间海景大床房，'
    '预算 ≤¥2200/晚。\n'
    '注意不可加价，要原报价。\n'
).encode('utf-8')


async def run():
    print("=" * 60)
    print("C3/C4 联调：邮件 → 解析 → API → 邮件回执")
    print("=" * 60)

    # 1) 解析邮件
    parser = EmailParser()
    parsed = parser.parse(SAMPLE_HOTEL)
    print(f"\n[1] 邮件解析结果")
    print(f"  from: {parsed.from_name} <{parsed.from_email}>")
    print(f"  subject: {parsed.subject}")
    print(f"  org: {parsed.organization}")
    print(f"  phone: {parsed.contact_number}")
    print(f"  scenario: {parsed.scenario}")
    print(f"  industry: {parsed.industry}")
    print(f"  constraints: {parsed.constraints}")
    print(f"  instruction: {parsed.instruction[:120]}")

    # 2) 调后端 API
    api = BackendClient()
    print(f"\n[2] 创建订单（POST /api/orders）")
    try:
        order = api.create_order(parsed)
        order_id = order["order_id"]
        print(f"  ✓ order_id: {order_id}")
        print(f"  status_url: {order.get('status_url')}")
        print(f"  intents: {len(order.get('intents', []))}")
    except Exception as e:
        print(f"  ✗ create failed: {e}")
        return

    # 3) 轮询等待
    print(f"\n[3] 等待 AI 处理（轮询中）")
    for i in range(20):
        time.sleep(3)
        o = api.get_order(order_id)
        print(f"  [{i*3+3:>3}s] status={o['status']}")
        if o["status"] in ("success", "failed", "needs_user"):
            break
    final = api.get_order(order_id)
    print(f"\n[4] 最终结果 status={final['status']}")
    result = final.get("result") or {}
    print(f"  summary: {result.get('summary', '(no summary)')[:200]}")
    print(f"  tried_strategies: {result.get('tried_strategies', [])}")
    if result.get("evaluation"):
        ev = result["evaluation"]
        print(f"  evaluation.total: {ev.get('total')}/100")
        for k, v in ev.get("dimensions", {}).items():
            print(f"    · {v.get('label', k)}: {v.get('score')}/{v.get('max')}")

    # 4) 构造回信
    print(f"\n[5] 构造回信")
    text, html = build_reply(parsed, final)
    print(f"  text 长度: {len(text)} chars")
    print(f"  html 长度: {len(html)} chars")
    print(f"\n  --- TEXT 邮件预览 ---")
    print(text[:1200])
    print(f"  ... (省略 {max(0, len(text)-1200)} chars)")

    # 5) 写盘（用于 C5 调试：实际 SMTP 发出前预览）
    out_dir = Path("data/email_outbox")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{order_id}.eml"
    out.write_text(
        f"From: AI 外贸代办 <aiagent@qq.com>\n"
        f"To: {parsed.from_email}\n"
        f"Subject: Re: {parsed.subject}\n"
        f"In-Reply-To: {parsed.message_id}\n"
        f"Content-Type: text/html; charset=utf-8\n"
        f"\n{html}",
        encoding="utf-8",
    )
    print(f"\n[6] 邮件已存盘: {out}（预览用，未实际发送）")
    print(f"\n✅ 联调通过")


if __name__ == "__main__":
    asyncio.run(run())

"""C 方案端到端验证：mock IMAP/SMTP，模拟客户发邮件 → worker 接收 → AI 处理 → 回信。

不开真实 QQ 邮箱，而是：
1) 起一个内存 IMAP mock（asyncio 队列模拟收件箱）
2) 注入一封客户邮件
3) 调 process_one() → 解析 → API → 回信
4) 验证回信内容（不实际发出，存在 data/email_outbox/）
"""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.email_worker import (
    EmailParser, IMAPClient, SMTPClient, BackendClient, build_reply,
    SMTP_USER, SMTP_FROM_NAME, process_one,
)


SAMPLE_HOTEL = (
    'From: "王老板" <wang@customer.com>\n'
    'To: aiagent@qq.com\n'
    'Subject: 帮我订上海外滩茂悦大酒店\n'
    'Message-ID: <e2e_c5@customer.com>\n'
    'Date: Mon, 10 Feb 2025 10:00:00 +0800\n'
    'Content-Type: text/plain; charset=utf-8\n'
    '\n'
    'AI 你好，客户要 4/10-4/12 入住上海外滩茂悦大酒店，'
    '2 晚 1 间豪华江景房，电话 +86-21-63239888，'
    '总预算 ≤¥4500。客户要求不可加价。\n'
).encode('utf-8')


SAMPLE_CABLE = (
    'From: "采购赵" <zhao@buyer.com>\n'
    'To: aiagent@qq.com\n'
    'Subject: 询价/远东电缆 YJV22 4×50\n'
    'Message-ID: <e2e_c5_cable@customer.com>\n'
    'Date: Tue, 11 Feb 2025 14:00:00 +0800\n'
    'Content-Type: text/plain; charset=utf-8\n'
    '\n'
    '帮我联系远东电缆厂，电话 0574-88336666，'
    '要询价 YJV22 4×50 铜芯电缆 5000 米，'
    'XLPE 绝缘，付款 30% TT 预付。\n'
    '要尽量压价。\n'
).encode('utf-8')


async def run_e2e():
    print("=" * 70)
    print("C 方案端到端验证：mock IMAP → 解析 → API → 构造回信")
    print("=" * 70)

    # === Mock IMAP：返回预设邮件 ===
    imap = IMAPClient.__new__(IMAPClient)
    imap.imap = MagicMock()
    test_emails = [
        (SAMPLE_HOTEL, b"1"),
        (SAMPLE_CABLE, b"2"),
    ]
    iter_idx = [0]

    def fake_fetch_unseen(batch: int = 10):
        if iter_idx[0] >= len(test_emails):
            return []
        result = test_emails[iter_idx[0]:iter_idx[0] + batch]
        iter_idx[0] += batch
        return result

    imap.fetch_unseen = fake_fetch_unseen
    imap.mark_seen = lambda mid: print(f"  [imap] mark_seen {mid!r}")

    # === Mock SMTP：截获 send() 不真发 ===
    smtp = SMTPClient.__new__(SMTPClient)
    smtp.smtp = MagicMock()
    sent = []

    def fake_send(from_email, to_email, subject, body_text, body_html=None, in_reply_to=None):
        sent.append({
            "from": from_email,
            "to": to_email,
            "subject": subject,
            "in_reply_to": in_reply_to,
            "text_len": len(body_text),
            "html_len": len(body_html or ""),
            "text_preview": body_text[:200],
        })
        # 存盘
        out_dir = Path("data/email_outbox")
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"c5_{iter_idx[0]}.eml"
        out.write_text(
            f"From: {SMTP_FROM_NAME} <{from_email}>\n"
            f"To: {to_email}\n"
            f"Subject: {subject}\n"
            f"In-Reply-To: {in_reply_to or ''}\n"
            f"Content-Type: text/html; charset=utf-8\n"
            f"\n{body_html or body_text}",
            encoding="utf-8",
        )
        print(f"  [smtp] saved → {out.name} ({len(body_text)}t / {len(body_html or '')}h)")

    smtp.send = fake_send

    # === BackendClient 真实联调 ===
    api = BackendClient()

    # 模拟 worker 主循环一次
    for raw, msg_id in imap.fetch_unseen():
        print(f"\n[--] 处理邮件 msg_id={msg_id!r} ({len(raw)} bytes)")
        await process_one(imap, smtp, api, raw, msg_id)

    # === 验证 ===
    print(f"\n{'='*70}")
    print(f"  验证结果：共发出 {len(sent)} 封回信")
    print(f"{'='*70}")
    for i, s in enumerate(sent, 1):
        print(f"\n  [{i}] From: {SMTP_FROM_NAME} <{s['from']}>")
        print(f"      To: {s['to']}")
        print(f"      Subject: {s['subject']}")
        print(f"      In-Reply-To: {s['in_reply_to']}")
        print(f"      Body: {s['text_len']} chars text, {s['html_len']} chars html")
        print(f"      Preview: {s['text_preview'][:150]}...")

    assert len(sent) == 2, f"expected 2 sent, got {len(sent)}"

    # 验证 1: hotel 邮件
    hotel_email = sent[0]
    assert "外滩茂悦" in hotel_email["text_preview"] or "上海" in hotel_email["text_preview"]
    assert hotel_email["in_reply_to"] == "<e2e_c5@customer.com>"
    assert hotel_email["to"] == "wang@customer.com"
    print(f"\n  ✓ hotel 邮件回信正确")

    # 验证 2: cable 邮件
    cable_email = sent[1]
    assert cable_email["to"] == "zhao@buyer.com"
    assert cable_email["in_reply_to"] == "<e2e_c5_cable@customer.com>"
    print(f"  ✓ cable 邮件回信正确")

    print(f"\n✅ C 方案端到端验证全部通过")


if __name__ == "__main__":
    asyncio.run(run_e2e())

"""C 方案邮件 worker 解析器单元测试。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.email_worker import EmailParser


SAMPLE_1 = (
    'From: "张经理" <zhang@example.com>\n'
    'To: aiagent@qq.com\n'
    'Subject: 帮我给南方大酒店打电话订一间大床房\n'
    'Message-ID: <test001@example.com>\n'
    'Date: Mon, 10 Feb 2025 10:00:00 +0800\n'
    'Content-Type: text/plain; charset=utf-8\n'
    '\n'
    '张经理，客户需要 3/15-6/3 14 夜客户，南方大酒店，'
    '电话 +86-20-83339999。'
    '房型可以动 "不可加价"。\n'
).encode('utf-8')


SAMPLE_2 = (
    'From: customer@163.com\n'
    'To: aiagent@qq.com\n'
    'Subject: 询价/电线电缆\n'
    'Message-ID: <test002@example.com>\n'
    'Date: Tue, 11 Feb 2025 14:00:00 +0800\n'
    'Content-Type: text/plain; charset=utf-8\n'
    '\n'
    '帮我联系宁波昌兴电缆厂，电话 0574-88338888，'
    '要询价 YJV22 4×50 电缆 2000 米，'
    '铜芯 XLPE 绝缘，付款方式 30% TT 预付。\n'
).encode('utf-8')


SAMPLE_3 = (
    'From: ops@factory.cn\n'
    'To: aiagent@qq.com\n'
    'Subject: Fw: Booking\n'
    'Message-ID: <test003@example.com>\n'
    'Date: Wed, 12 Feb 2025 09:00:00 +0800\n'
    'Content-Type: multipart/mixed; boundary="BOUND"\n'
    '\n'
    '--BOUND\n'
    'Content-Type: text/plain; charset=utf-8\n'
    '\n'
    '请处理预订。\n'
    '\n'
    '--BOUND\n'
    'Content-Type: message/rfc822\n'
    'Content-Disposition: attachment; filename="thread.eml"\n'
    '\n'
    'From: hotel@hilton.com\n'
    'To: ops@factory.cn\n'
    'Subject: Re: Booking\n'
    'Date: Tue, 11 Feb 2025 18:00:00 +0800\n'
    '\n'
    'Your booking 12345 is confirmed at $200/night.\n'
    '\n'
    '--BOUND--\n'
).encode('utf-8')


def test_basic():
    p = EmailParser()
    r = p.parse(SAMPLE_1)
    assert r.from_email == "zhang@example.com", r.from_email
    assert r.from_name == "张经理", r.from_name
    assert "南方大酒店" in r.subject
    assert "客户需要" in r.instruction
    print(f"  ✓ from={r.from_email} name={r.from_name}")
    print(f"  ✓ subject={r.subject}")
    print(f"  ✓ instruction[:60]={r.instruction[:60]}")
    # org / phone / constraint / scenario
    assert r.contact_number == "+862083339999" or r.contact_number == "+86-20-83339999", f"phone={r.contact_number}"
    assert r.scenario == "hotel", r.scenario
    assert r.constraints and "加价" in r.constraints, f"constraint={r.constraints}"
    print(f"  ✓ phone={r.contact_number} scenario={r.scenario} constraint={r.constraints}")


def test_industry():
    p = EmailParser()
    r = p.parse(SAMPLE_2)
    assert r.industry == "cable", f"industry={r.industry}"
    assert r.scenario in ("sample_confirm", "price_negotiation"), f"scenario={r.scenario}"
    assert "宁波昌兴电缆厂" in r.organization or r.organization is None
    assert r.contact_number and "574" in r.contact_number, f"phone={r.contact_number}"
    print(f"  ✓ industry={r.industry} scenario={r.scenario} org={r.organization} phone={r.contact_number}")


def test_thread_attachment():
    p = EmailParser()
    r = p.parse(SAMPLE_3)
    assert len(r.thread) == 1, f"thread_len={len(r.thread)}"
    assert r.thread[0]["from"] == "hotel@hilton.com"
    assert "12345" in r.thread[0]["body"]
    print(f"  ✓ thread len={len(r.thread)} first from={r.thread[0]['from']}")


if __name__ == "__main__":
    print("TEST 1: basic hotel email")
    test_basic()
    print("\nTEST 2: cable industry")
    test_industry()
    print("\nTEST 3: thread .eml attachment")
    test_thread_attachment()
    print("\n✅ ALL PASS")

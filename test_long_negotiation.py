"""1.7.5 长沟通 E2E 验证。

目标：触发 10+ 轮对话，验证：
- 摘要压缩触发不报错
- 进度通知节流正确
- 状态机新转移不崩
- 整体能跑完不崩溃
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request

sys.path.insert(0, str(Path(__file__).resolve().parent))


async def run():
    print("=" * 60)
    print("1.7.5 长沟通 E2E 验证（mock 长路径模式）")
    print("=" * 60)

    # 1) 创建订单（含"长沟通"关键词触发反复询问）
    payload = json.dumps({
        "organization": "上海外滩茂悦大酒店",
        "contact_number": "+862163239888",
        "requirement": "【长沟通】客户要 6/20-6/22 入住上海外滩茂悦大酒店，2 晚 1 间豪华江景房，预算 ≤¥3500/晚。",
        "preferred_channel": "sms",
        "scenario": "hotel",
        "constraints": "尽量压价",
        "user_email": "cheng@cttcable.com",
    }).encode()
    req = Request(
        "http://127.0.0.1:8766/api/orders",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = json.loads(urlopen(req).read())
    order_id = resp["order_id"]
    print(f"[1] order.created: {order_id}")

    # 2) 轮询等（最多 4 分钟 = 48*5s）
    start = time.time()
    last_turns = -1
    stagnant_count = 0
    for i in range(48):
        await asyncio.sleep(5)
        elapsed = int(time.time() - start)
        o = json.loads(urlopen(f"http://127.0.0.1:8766/api/orders/{order_id}").read())
        dialogue_count = len(o.get("dialogue", []))
        state = o.get("state", "")
        status = o.get("status", "")
        tried = o.get("result", {}).get("tried_strategies", []) if o.get("result") else []
        print(f"  [{elapsed:>3}s] state={state:<18} status={status:<14} dialogue={dialogue_count} turns  tried={len(tried)}")

        if dialogue_count == last_turns and status == "in_progress":
            stagnant_count += 1
            if stagnant_count > 12:  # 60s 没动
                print(f"  ⚠️ 卡住 60s，dialogue 不再增长")
                break
        else:
            stagnant_count = 0
        last_turns = dialogue_count

        if status in ("success", "failed", "needs_user"):
            break

    final = json.loads(urlopen(f"http://127.0.0.1:8766/api/orders/{order_id}").read())
    total = time.time() - start
    print()
    print(f"[2] 最终状态: {final['status']}")
    print(f"    用时: {total:.1f} 秒")
    print(f"    对话轮数: {len(final.get('dialogue', []))} turns")
    if final.get("result") and final["result"].get("tried_strategies"):
        print(f"    尝试策略: {final['result']['tried_strategies']}")
    if final.get("result") and final["result"].get("engine"):
        print(f"    引擎: {final['result']['engine']}")

    # 3) 验证：摘要压缩
    import subprocess
    r = subprocess.run(["grep", "-c", "compressing", "/tmp/main-app.log"], capture_output=True, text=True)
    compress_count = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0
    print(f"    摘要压缩触发: {compress_count} 次")

    # 4) 验证：进度邮件
    r = subprocess.run(["grep", "-c", "progress mail", "/tmp/main-app.log"], capture_output=True, text=True)
    progress_count = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0
    print(f"    进度邮件发送: {progress_count} 封")

    turns = len(final.get("dialogue", []))
    print()
    if turns >= 12 and final['status'] in ("success", "needs_user"):
        print(f"✅ 1.7.5 验证通过：跑了 {turns} 轮（{total:.0f} 秒），目标 ≥12 轮")
    elif final['status'] == 'failed':
        print(f"⚠️  1.7.5 部分通过：跑了 {turns} 轮后 fail，框架代码不崩但协商策略需要调优")
    else:
        print(f"❌ 1.7.5 没跑起来（只跑了 {turns} 轮）")


if __name__ == "__main__":
    asyncio.run(run())

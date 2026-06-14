"""V2.0 真 LLM vs V1.2 规则对比。

直接调 LLM 决策函数 + V1.2 fallback，对 4 个高难度 case 给策略选择。
看 LLM 是不是比规则更聪明。

固定 4 个高难度 case：
1. 酒店·用户硬约束"不可加价" + 商家加价 24% > 阈值 20%
2. 租车·无约束 + 商家加价 35% > 阈值 30%
3. 机票·旺季改签 + 大幅加价 ¥35000 > 阈值 ¥30000
4. 酒店·用户硬约束"不可加价" + 商家日期也满
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.core.llm_negotiator import (
    call_llm_for_negotiation,
    fallback_strategy_decision,
)
from backend.core.negotiation import NegotiationContext


CASES = [
    {
        "name": "Case 1: 酒店·用户硬约束+加价超阈",
        "scenario": "hotel",
        "ctx": NegotiationContext(
            scenario="hotel", round_count=1,
            user_constraints="不可加价",
            price_change_pct=24, price_change_abs=4800,
            last_merchant_text="申し訳ございません。6月12日のツインルームは満室でございます。デラックスルームでしたら追加料金1泊4,800円で承ります。",
            last_strategy_id=None, tried_strategies=[]
        ),
        "req": "帮我致电酒店改入住 6.12 双床+免费早餐",
        "lang": "ja",
        "org": "大阪心斋桥大和鲁内酒店",
        "merchant_last": "[MERCHANT] (ja) 申し訳ございません。6月12日のツインルームは満室でございます。デラックスルームでしたら追加料金1泊4,800円で承ります。",
    },
    {
        "name": "Case 2: 租车·无约束+加价超阈",
        "scenario": "car_rental",
        "ctx": NegotiationContext(
            scenario="car_rental", round_count=1,
            user_constraints=None,
            price_change_pct=35, price_change_abs=2400,
            last_merchant_text="We only have SUV available for 3 days, total is $580, 35% more than your budget.",
            last_strategy_id=None, tried_strategies=[]
        ),
        "req": "I need an economy car for 3 days at the airport.",
        "lang": "en",
        "org": "Hertz Honolulu",
        "merchant_last": "[MERCHANT] (en) We only have SUV available for 3 days, total is $580, 35% more than your budget.",
    },
    {
        "name": "Case 3: 机票·旺季改签+大幅加价",
        "scenario": "flight",
        "ctx": NegotiationContext(
            scenario="flight", round_count=1,
            user_constraints=None,
            price_change_pct=42, price_change_abs=35000,
            last_merchant_text="Flight NH107 on June 15: business class upgrade is required, additional ¥35,000.",
            last_strategy_id=None, tried_strategies=[]
        ),
        "req": "Please change my flight to June 15, peak season upgrade.",
        "lang": "en",
        "org": "ANA Customer Service",
        "merchant_last": "[MERCHANT] (en) Flight NH107 on June 15: business class upgrade is required, additional ¥35,000.",
    },
    {
        "name": "Case 4: 酒店·硬约束+日期也满",
        "scenario": "hotel",
        "ctx": NegotiationContext(
            scenario="hotel", round_count=2,
            user_constraints="不可加价",
            price_change_pct=20, price_change_abs=4000,
            last_merchant_text="6月12日、6月13日ともにツインルームは満室でございます。デラックスタイプでしたら追加料金で対応可能です。",
            last_strategy_id="hold_position", tried_strategies=["hold_position"]
        ),
        "req": "帮我致电酒店改入住 6.12 双床+免费早餐",
        "lang": "ja",
        "org": "大阪心斋桥大和鲁内酒店",
        "merchant_last": "[MERCHANT] (ja) 6月12日、6月13日ともにツインルームは満室でございます。デラックスタイプでしたら追加料金で対応可能です。",
    },
]


async def main():
    print("=" * 80)
    print("V2.0 真 LLM (MiniMax-M3) vs V1.2 规则 策略选择对比")
    print("=" * 80)

    for i, c in enumerate(CASES, 1):
        print(f"\n{'─'*80}")
        print(f"📋 {c['name']}")
        print(f"   用户约束: {c['ctx'].user_constraints or '（无）'}")
        print(f"   商家加价: +{c['ctx'].price_change_pct}% / +{c['ctx'].price_change_abs}")
        print(f"   已用策略: {c['ctx'].tried_strategies or '（首次）'}")

        # V1.2 规则
        v12_id = fallback_strategy_decision(c["ctx"])
        v12_strategy = {
            "hold_position": "坚持原条件（用户硬约束）",
            "alt_date": "替代日期（日期问题）",
            "value_trade": "增值让步（价格坚守）",
            "chain_offer": "链式反提案（无约束可打包）",
            "loyalty": "忠诚度换价（回头客）",
            "walk_away": "提前离场（多轮无效）",
            "escalate": "升级用户（超阈值）",
        }.get(v12_id, v12_id)
        print(f"\n  🔧 V1.2 规则 →  {v12_id}  ({v12_strategy})")

        # 真 LLM
        dialogue = [{"speaker": "ai", "text": f"Hi, I'd like to {c['req']}", "lang": c["lang"]},
                    {"speaker": "merchant", "text": c["ctx"].last_merchant_text, "lang": c["lang"]}]

        try:
            r = await call_llm_for_negotiation(
                dialogue, c["ctx"], c["req"], c["ctx"].user_constraints, c["lang"], c["org"]
            )
            if r:
                llm_id = r.get("strategy_id", "?")
                print(f"  🧠 M3 LLM →   {llm_id}")
                print(f"     reasoning: {r.get('reasoning', '')[:120]}")
                speech = r.get("ai_speech", "")
                if speech:
                    print(f"     ai_speech: {speech[:120]}{'...' if len(speech)>120 else ''}")
                print(f"     outcome_guess: {r.get('merchant_outcome_guess', '?')} | pct_guess: {r.get('new_price_pct_guess', '?')}")
                match = "✅ 一致" if llm_id == v12_id else "🆕 LLM 给了不同答案"
                print(f"     → {match}")
            else:
                print(f"  🧠 M3 LLM →   （调用失败或解析失败，降级 V1.2）")
        except Exception as e:
            print(f"  🧠 M3 LLM →   异常: {e}")


if __name__ == "__main__":
    asyncio.run(main())

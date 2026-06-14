"""V2.1 AI 表现评估器。

每单跑完后异步调用，按 5 维评分：
  1. 商务话术（敬语/语气/目标语种地道度）· 25 分
  2. 策略选优（V1.2 基线 vs 实际 LLM 决策差距）· 25 分
  3. 让步幅度（最终加价 vs 商家原报价）· 20 分
  4. 对话效率（轮数 vs 场景平均）· 15 分
  5. 商家满意度（语气/情绪识别）· 15 分

输出：总分 0-100 + 5 维分 + 雷达图数据 + 改进建议

评估 LLM 复用 MiniMax-M3。降级时用启发式规则。
"""
from __future__ import annotations
import json
import os
import re
from typing import Optional
from dataclasses import dataclass, asdict
from ..llm_client import call_mavis_llm, extract_json_from_text
from ..models import Order, OrderState, OrderStatus
from .negotiation import NegotiationContext
from .llm_negotiator import fallback_strategy_decision, fallback_outcome_assessment
from ..knowledge.negotiation_strategies import SCENARIO_ESCALATION_THRESHOLDS


# 场景对话轮数基线（V1.0 端到端测试均值）
SCENARIO_ROUND_BASELINE = {
    "hotel": 4.0,        # 一般 4 轮：开场 + 1-2 确认 + 0-1 协商
    "car_rental": 3.0,
    "flight": 4.0,
}


@dataclass
class EvaluationScore:
    """5 维评分 + 总分。"""
    etiquette: int = 0        # 商务话术 25
    strategy: int = 0         # 策略选优 25
    concession: int = 0       # 让步幅度 20
    efficiency: int = 0       # 对话效率 15
    satisfaction: int = 0     # 商家满意度 15
    total: int = 0            # 总分 0-100

    breakdown: dict = None    # 每维详细理由
    suggestions: list = None  # 改进建议
    engine: str = ""          # "M3 LLM" / "fallback"


# === 评估 prompt ===
EVAL_PROMPT = """你是一位资深的跨境商务沟通质量评估专家，专注于帮产品团队找出 AI 客户经理哪里做得好、哪里需要改进。

## 任务

对以下「AI 客户经理 vs 境外商家」的多轮对话，按 5 维评分，每维给出 0-满分 的整数分数，并附 1-2 句判断理由。

## 5 维评分标准

### 1. etiquette（商务话术，满分 25）
- 目标语种敬语体系是否到位（日本語敬语 / 商务英文正式度 / 韩语 존댓말）
- 语气是否专业礼貌但不机械
- 是否避免了中式英文/中式日语等不地道表达
- 是否在多轮中保持称呼一致

### 2. strategy（策略选优，满分 25）
- 第一轮策略是否最佳开局
- 商家回应后，AI 是否及时调整策略（不死磕、不过早放弃）
- 策略顺序是否合理（先守后攻，先软后硬）
- 是否在合适时机收单 / 升级

### 3. concession（让步幅度，满分 20）
- 商家加价 X%，AI 最终谈到 Y%
- 评分：0% 让步=20 分，每多 1% 商家坚持 = -0.4 分（最高扣 20）
- 如果升级到用户 = 0 分（AI 没自己搞定）
- 如果商家主动让步 = 加 1-3 分

### 4. efficiency（对话效率，满分 15）
- 总轮数 vs 场景平均（hotel 4 轮 / 租车 3 轮 / 机票 4 轮）
- 评分：达到平均 = 15 分，每多 1 轮 -3 分，每少 1 轮 +1.5 分
- 如果有废话轮（重复确认/无效沟通）= 减 2-5 分

### 5. satisfaction（商家满意度，满分 15）
- 从商家最后 1-2 轮的语气判断
- 关键词：积极（ご利用いただけます/喜んで/understood/perfect/glad）= 高
- 中性（承知いたしました/I see）= 中
- 消极（無理/申し訳ございません/sorry/can't）= 低
- 商家主动让步或提供替代 = +2-3 分

## 输出要求

严格返回 JSON：

```json
{{
  "etiquette": 0-25,
  "strategy": 0-25,
  "concession": 0-20,
  "efficiency": 0-15,
  "satisfaction": 0-15,
  "breakdown": {{
    "etiquette_reason": "中文 1 句",
    "strategy_reason": "中文 1 句",
    "concession_reason": "中文 1 句",
    "efficiency_reason": "中文 1 句",
    "satisfaction_reason": "中文 1 句"
  }},
  "suggestions": ["改进建议 1", "改进建议 2", "改进建议 3"]
}}
```

## 待评估数据

- 用户需求：{requirement}
- 用户约束：{constraints}
- 场景：{scenario}
- 目标语种：{lang}
- 最终状态：{status}
- 对话轮数：{rounds}
- 商家加价峰值：+{max_price_pct}%
- 商家加价绝对：+¥{max_price_abs}
- 已用策略：{tried_strategies}

## 完整对话

{dialogue}

请评估。返回 JSON。"""


def _format_dialogue(order: Order) -> str:
    """把 Order 的 dialogue 序列化成评估 prompt 用字符串。"""
    lines = []
    for t in order.dialogue:
        speaker = "AI" if t.speaker == "ai" else "商家"
        if t.speaker == "merchant" and t.original != t.translated:
            lines.append(f"[{speaker}] {t.original}  // 译文：{t.translated}")
        else:
            lines.append(f"[{speaker}] {t.original}")
    return "\n".join(lines) if lines else "（无对话）"


def _heuristic_evaluate(order: Order) -> EvaluationScore:
    """降级路径：LLM 不可用时用启发式。"""
    s = EvaluationScore()
    s.engine = "fallback-heuristic"
    s.breakdown = {}
    s.suggestions = []

    dialogue = order.dialogue
    n_rounds = len(dialogue) // 2
    ai_turns = [t for t in dialogue if t.speaker == "ai"]
    mer_turns = [t for t in dialogue if t.speaker == "merchant"]

    # 1. etiquette 基础分：长度合理 + 没机械重复
    avg_len = sum(len(t.original) for t in ai_turns) / max(len(ai_turns), 1)
    s.etiquette = 20 if 30 <= avg_len <= 200 else 14
    s.breakdown["etiquette_reason"] = f"AI 平均 {avg_len:.0f} 字/轮，{'合理' if 30 <= avg_len <= 200 else '偏短或偏长'}"

    # 2. strategy：是否触发协商
    tried = (order.result or {}).get("tried_strategies", [])
    if order.status == OrderStatus.SUCCESS and not tried:
        s.strategy = 22  # 简单单直接成交
        s.breakdown["strategy_reason"] = "无协商需求，AI 直达成交，效率高"
    elif tried and order.status == OrderStatus.SUCCESS:
        s.strategy = 18
        s.breakdown["strategy_reason"] = f"使用 {len(tried)} 个策略后成交，路径合理"
    elif order.status == OrderStatus.NEEDS_USER:
        s.strategy = 12
        s.breakdown["strategy_reason"] = "升级到用户，AI 未搞定"
        s.suggestions.append("考虑加 1-2 轮再升级，给商家更明确让步信号")
    else:
        s.strategy = 8
        s.breakdown["strategy_reason"] = "未成交，策略路径有改进空间"

    # 3. concession：让步幅度
    result = order.result or {}
    max_pct = result.get("max_price_pct", 0)
    if order.status == OrderStatus.NEEDS_USER:
        s.concession = 0
        s.breakdown["concession_reason"] = "升级用户 = 0 分"
    elif order.status == OrderStatus.SUCCESS and max_pct == 0:
        s.concession = 20
        s.breakdown["concession_reason"] = "商家未加价，原条件成交"
    elif order.status == OrderStatus.SUCCESS:
        # 加价 X%，AI 谈下来 Y% 假设一致（mock 简化）
        s.concession = max(0, 20 - int(max_pct * 0.4))
        s.breakdown["concession_reason"] = f"加价 {max_pct:.0f}%，AI 维持原加价成交"
    else:
        s.concession = 0
        s.breakdown["concession_reason"] = "未成交"

    # 4. efficiency：轮数 vs 基线
    baseline = SCENARIO_ROUND_BASELINE.get(order.scenario, 4.0)
    if n_rounds <= baseline:
        s.efficiency = 15
    else:
        s.efficiency = max(0, 15 - int((n_rounds - baseline) * 3))
    s.breakdown["efficiency_reason"] = f"用了 {n_rounds} 轮，场景基线 {baseline} 轮"

    # 5. satisfaction：商家最后一句
    if mer_turns:
        last_mer = mer_turns[-1].original.lower()
        positive = ["ご利用", "understood", "perfect", "glad", "happy", "ありがとう", "承知", "available"]
        negative = ["無理", "申し訳", "sorry", "can't", "impossible", "できません", "않", "죄송"]
        if any(kw in last_mer for kw in positive):
            s.satisfaction = 13
            s.breakdown["satisfaction_reason"] = "商家语气积极"
        elif any(kw in last_mer for kw in negative):
            s.satisfaction = 5
            s.breakdown["satisfaction_reason"] = "商家语气消极"
        else:
            s.satisfaction = 9
            s.breakdown["satisfaction_reason"] = "商家语气中性"
    else:
        s.satisfaction = 8
        s.breakdown["satisfaction_reason"] = "无商家回复"

    s.total = s.etiquette + s.strategy + s.concession + s.efficiency + s.satisfaction
    if not s.suggestions:
        if s.efficiency < 12:
            s.suggestions.append("减少重复确认轮，合并询问多意图项")
        if s.concession < 10:
            s.suggestions.append("升级前再尝试一次 chain_offer 或 value_trade 策略")
    return s


async def evaluate_order(order: Order) -> EvaluationScore:
    """评估一个订单的 AI 表现。返回 EvaluationScore。

    优先用 LLM；不可用时降级到启发式。
    """
    result = order.result or {}
    max_pct = float(result.get("max_price_pct", 0))
    max_abs = float(result.get("max_price_abs", 0))
    tried = result.get("tried_strategies", [])
    rounds = len(order.dialogue) // 2

    prompt = EVAL_PROMPT.format(
        requirement=order.requirement,
        constraints=order.constraints or "无",
        scenario=order.scenario,
        lang=order.target_language,
        status=order.status.value,
        rounds=rounds,
        max_price_pct=f"{max_pct:.0f}",
        max_price_abs=f"{max_abs:.0f}",
        tried_strategies=", ".join(tried) if tried else "（无）",
        dialogue=_format_dialogue(order)[:3500],  # 截断避免超长
    )

    try:
        content = await call_mavis_llm(
            system="你是商务沟通质量评估专家。只返回严格 JSON。",
            user=prompt,
            max_tokens=600,
            temperature=0.2,
        )
        if not content:
            return _heuristic_evaluate(order)

        data = extract_json_from_text(content)
        if not data:
            return _heuristic_evaluate(order)

        # 校验范围
        s = EvaluationScore(
            etiquette=max(0, min(25, int(data.get("etiquette", 0)))),
            strategy=max(0, min(25, int(data.get("strategy", 0)))),
            concession=max(0, min(20, int(data.get("concession", 0)))),
            efficiency=max(0, min(15, int(data.get("efficiency", 0)))),
            satisfaction=max(0, min(15, int(data.get("satisfaction", 0)))),
            breakdown=data.get("breakdown", {}),
            suggestions=data.get("suggestions", [])[:5],
            engine="MiniMax-M3",
        )
        s.total = s.etiquette + s.strategy + s.concession + s.efficiency + s.satisfaction
        return s
    except Exception:
        return _heuristic_evaluate(order)


def score_to_dict(s: EvaluationScore) -> dict:
    """转成可序列化 dict。"""
    return {
        "total": s.total,
        "engine": s.engine,
        "dimensions": {
            "etiquette": {"score": s.etiquette, "max": 25, "label": "商务话术"},
            "strategy": {"score": s.strategy, "max": 25, "label": "策略选优"},
            "concession": {"score": s.concession, "max": 20, "label": "让步幅度"},
            "efficiency": {"score": s.efficiency, "max": 15, "label": "对话效率"},
            "satisfaction": {"score": s.satisfaction, "max": 15, "label": "商家满意度"},
        },
        "breakdown": s.breakdown or {},
        "suggestions": s.suggestions or [],
        "radar": [
            s.etiquette / 25 * 100,
            s.strategy / 25 * 100,
            s.concession / 20 * 100,
            s.efficiency / 15 * 100,
            s.satisfaction / 15 * 100,
        ],
    }

"""协商决策引擎：根据上下文选下一步策略。

输入：当前状态（轮数 / 用户约束 / 商家上轮回复 / 已尝试策略）
输出：下一个策略（STRATEGY_HOLD / ALT_DATE / VALUE_TRADE / CHAIN_OFFER / LOYALTY / WALK_AWAY / ESCALATE）
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from ..knowledge.negotiation_strategies import (
    Strategy, ALL_STRATEGIES, STRATEGY_BY_ID,
    STRATEGY_HOLD, STRATEGY_ALT_DATE, STRATEGY_VALUE_TRADE,
    STRATEGY_CHAIN_OFFER, STRATEGY_LOYALTY, STRATEGY_WALK_AWAY,
    SCENARIO_ESCALATION_THRESHOLDS, MAX_NEGOTIATION_ROUNDS,
)


@dataclass
class NegotiationContext:
    """协商上下文（每轮更新）。"""
    scenario: str  # hotel/car_rental/flight
    round_count: int  # 当前已协商轮数
    user_constraints: str | None  # 用户硬约束原文
    price_change_pct: float  # 商家提的加价百分比
    price_change_abs: float  # 加价绝对金额
    last_merchant_text: str  # 商家最近一次回复
    last_strategy_id: str | None  # 上一轮 AI 用的策略
    tried_strategies: List[str] = field(default_factory=list)  # 已用过的策略
    bundle_items: List[str] = field(default_factory=list)  # 链式反提案可用的 bundle 项


def detect_constraints(constraints: str | None) -> Dict[str, bool]:
    """解析用户硬约束成结构化标签。"""
    if not constraints:
        return {"no_price_increase": False, "must_free_cancel": False, "no_secondary_fees": False, "has_constraint": False}
    return {
        "no_price_increase": any(kw in constraints for kw in ["不可加价", "不加价", "no increase", "no price", "no markup"]),
        "must_free_cancel": any(kw in constraints for kw in ["必须免费取消", "免费取消", "free cancel"]),
        "no_secondary_fees": any(kw in constraints for kw in ["无附加费", "不收附加", "no surcharge"]),
        "has_constraint": True,
    }


def should_walk_away(ctx: NegotiationContext) -> bool:
    """判断是否应该主动 walk away（避免无限拉锯）。"""
    if ctx.round_count >= MAX_NEGOTIATION_ROUNDS:
        return True
    # 如果价格变化离谱（>50%）且已用 2+ 策略
    if ctx.price_change_pct > 50 and len(ctx.tried_strategies) >= 2:
        return True
    return False


def should_escalate(ctx: NegotiationContext) -> tuple[bool, str]:
    """判断是否升级用户。返回 (是否升级, 原因)。"""
    if ctx.price_change_pct <= 0 and ctx.price_change_abs <= 0:
        return False, ""

    thresholds = SCENARIO_ESCALATION_THRESHOLDS.get(
        ctx.scenario, SCENARIO_ESCALATION_THRESHOLDS["hotel"]
    )
    threshold_pct = thresholds["price_change_pct"]
    threshold_abs = thresholds["price_change_abs"]

    if ctx.price_change_pct > threshold_pct:
        return True, f"加价 {ctx.price_change_pct:.0f}% 超过 {ctx.scenario} 阈值 {threshold_pct}%"
    if ctx.price_change_abs > threshold_abs:
        return True, f"加价 ¥{ctx.price_change_abs:.0f} 超过 {ctx.scenario} 阈值 ¥{threshold_abs:.0f}"
    return False, ""


def choose_strategy(ctx: NegotiationContext) -> Optional[Strategy]:
    """根据上下文选下一个策略。返回 None 表示该 ESCALATE。

    策略选择优先级：
    1. 如果 round_count >= MAX：WALK_AWAY
    2. 如果商家明确坚持（failure_signals 命中）+ price 离谱：WALK_AWAY
    3. 如果用户有"不可加价"约束 + 商家提加价：HOLD_POSITION（第一选择）
    4. 如果日期相关：ALT_DATE（如果还没用）
    5. 如果已经用过 HOLD/ALT_DATE 但失败：CHAIN_OFFER（带 bundle_items）
    6. 如果是重复客户场景（round >= 2）+ 还没用：LOYALTY
    7. 如果策略都试过：WALK_AWAY
    """
    constraints = detect_constraints(ctx.user_constraints)

    # 1) Round 太多 → walk away
    if should_walk_away(ctx):
        return STRATEGY_WALK_AWAY

    # 2) 商家已明显拒绝 + 价格离谱
    last_lower = (ctx.last_merchant_text or "").lower()
    rejected_explicitly = _match_signals(last_lower, STRATEGY_HOLD.failure_signals.get(ctx.scenario, []) or STRATEGY_HOLD.failure_signals.get("en", []))
    if rejected_explicitly and ctx.price_change_pct > 50 and len(ctx.tried_strategies) >= 2:
        return STRATEGY_WALK_AWAY

    # 3) 用户有"不可加价"约束 + 商家提加价
    if constraints["no_price_increase"] and ctx.price_change_abs > 0:
        if "hold_position" not in ctx.tried_strategies:
            return STRATEGY_HOLD
        # HOLD 用过还失败 → 链式反提案
        if "chain_offer" not in ctx.tried_strategies and ctx.bundle_items:
            return STRATEGY_CHAIN_OFFER
        return STRATEGY_WALK_AWAY

    # 4) 日期冲突 → ALT_DATE
    if "alt_date" not in ctx.tried_strategies and _is_date_conflict(ctx):
        return STRATEGY_ALT_DATE

    # 5) 商家提加价但没拒绝：CHAIN_OFFER（带 bundle_items）
    if "chain_offer" not in ctx.tried_strategies and ctx.bundle_items and ctx.price_change_abs > 0:
        return STRATEGY_CHAIN_OFFER

    # 6) VALUE_TRADE：如果商家坚守价格但 flexible
    if "value_trade" not in ctx.tried_strategies and ctx.price_change_abs > 0 and ctx.round_count >= 1:
        return STRATEGY_VALUE_TRADE

    # 7) LOYALTY：第二轮 + 还没用
    if "loyalty" not in ctx.tried_strategies and ctx.round_count >= 2:
        return STRATEGY_LOYALTY

    # 8) 都用过了或没有合适策略 → walk away
    return STRATEGY_WALK_AWAY


def _is_date_conflict(ctx: NegotiationContext) -> bool:
    """判断是否日期冲突（商家说某日不可）。"""
    text = (ctx.last_merchant_text or "").lower()
    conflict_keywords = {
        "hotel": ["fully booked", "満室", "만실", "sold out", "unavailable", "不可", "이용 불가"],
        "car_rental": ["sold out", "満車", "만석", "no car", "車両なし"],
        "flight": ["no flight", "満席", "만석", "sold out", "no availability"],
    }
    return any(kw in text for kw in conflict_keywords.get(ctx.scenario, []))


def _match_signals(text_lower: str, signals: List[str]) -> bool:
    """检查 text 是否包含 signals 中任一关键词。"""
    return any(sig.lower() in text_lower for sig in signals)


def record_strategy_result(
    ctx: NegotiationContext,
    strategy_id: str,
    merchant_text: str,
    new_price_change_pct: float,
    new_price_change_abs: float,
) -> NegotiationContext:
    """记录策略执行结果，更新 ctx 用于下一轮决策。"""
    strategy = STRATEGY_BY_ID.get(strategy_id)
    succeeded = False
    if strategy and strategy.success_signals:
        sigs = strategy.success_signals.get(ctx.scenario, []) or strategy.success_signals.get("en", [])
        if _match_signals(merchant_text.lower(), sigs):
            succeeded = True

    ctx.tried_strategies.append(strategy_id)
    ctx.last_merchant_text = merchant_text
    ctx.last_strategy_id = strategy_id
    ctx.price_change_pct = new_price_change_pct
    ctx.price_change_abs = new_price_change_abs
    ctx.round_count += 1
    ctx._last_strategy_succeeded = succeeded
    return ctx

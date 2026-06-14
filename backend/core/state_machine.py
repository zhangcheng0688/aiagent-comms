"""状态机：10 个状态 + 转移条件 + 场景化升级阈值（V1.2）。"""
from __future__ import annotations
from dataclasses import dataclass
from ..models import OrderState
# 升级阈值改用 negotiation 里的场景化版本
from .negotiation import should_escalate, MAX_NEGOTIATION_ROUNDS
# 兼容旧 import
from ..knowledge.negotiation_strategies import MAX_NEGOTIATION_ROUNDS as _MAX_ROUNDS  # noqa


@dataclass
class StateTransition:
    from_state: OrderState
    to_state: OrderState
    trigger: str
    ai_action: str


TRANSITIONS: list[StateTransition] = [
    StateTransition(OrderState.INIT, OrderState.CONNECTING, "submit", "拨号/发短信"),
    StateTransition(OrderState.CONNECTING, OrderState.OPENING, "connected", "礼貌开场+自我介绍"),
    StateTransition(OrderState.OPENING, OrderState.CONFIRMING, "merchant_ready", "按 priority 顺序逐项确认诉求"),
    StateTransition(OrderState.CONFIRMING, OrderState.NEGOTIATING, "merchant_pushback", "进入多轮协商"),
    StateTransition(OrderState.CONFIRMING, OrderState.CLOSING_SUCCESS, "all_confirmed", "所有诉求确认，结束"),
    # NEGOTIATING 内部子状态：PROBING → COUNTER_OFFER → ACCEPTING / REJECTING
    StateTransition(OrderState.NEGOTIATING, OrderState.NEGOTIATING, "probe", "继续问询（hold / alt_date）"),
    StateTransition(OrderState.NEGOTIATING, OrderState.NEGOTIATING, "counter_offer", "AI 反提案（chain / value / loyalty）"),
    StateTransition(OrderState.NEGOTIATING, OrderState.CLOSING_SUCCESS, "compromise_reached", "达成一致，结束"),
    StateTransition(OrderState.NEGOTIATING, OrderState.CLOSING_FAILURE, "deadlock", "协商僵局，结束"),
    StateTransition(OrderState.NEGOTIATING, OrderState.AWAIT_USER, "escalation_triggered", "推送用户决策"),
    StateTransition(OrderState.NEGOTIATING, OrderState.CLOSING_FAILURE, "walk_away", "AI 主动离场"),
    StateTransition(OrderState.AWAIT_USER, OrderState.NEGOTIATING, "user_response", "用户决策返回，继续"),
    StateTransition(OrderState.AWAIT_USER, OrderState.CLOSING_FAILURE, "user_abort", "用户主动取消"),
    StateTransition(OrderState.ESCALATE_TO_USER, OrderState.AWAIT_USER, "user_pinged", "已推送用户，等待响应"),
    StateTransition(OrderState.CONNECTING, OrderState.ABORTED, "no_answer_3x", "3 次未接通，中止"),
    StateTransition(OrderState.NEGOTIATING, OrderState.CLOSING_FAILURE, "merchant_reject", "商家明确拒绝"),
    # === 1.7.2 长沟通转移 ===
    StateTransition(OrderState.NEGOTIATING, OrderState.AWAIT_MERCHANT, "merchant_need_time", "商家说'我查一下'，等"),
    StateTransition(OrderState.AWAIT_MERCHANT, OrderState.NEGOTIATING, "merchant_responded", "商家回复了，继续"),
    StateTransition(OrderState.AWAIT_MERCHANT, OrderState.CLOSING_FAILURE, "merchant_timeout", "商家超时未回复"),
    StateTransition(OrderState.NEGOTIATING, OrderState.PAUSED, "user_pause", "用户主动暂停（'等我问问老板'）"),
    StateTransition(OrderState.CONFIRMING, OrderState.PAUSED, "user_pause", "用户主动暂停"),
    StateTransition(OrderState.AWAIT_MERCHANT, OrderState.PAUSED, "user_pause", "用户主动暂停"),
    StateTransition(OrderState.PAUSED, OrderState.RESUMED, "user_resume", "用户说继续"),
    StateTransition(OrderState.RESUMED, OrderState.NEGOTIATING, "auto_continue", "自动跳回协商态"),
]


# V1.2 兼容旧调用
def should_escalate_legacy(
    round_count: int,
    price_change_pct: float | None,
    price_change_abs: float | None,
    sensitive_info_requested: bool,
    user_constraint_violated: bool,
) -> tuple[bool, str]:
    """旧 API 兼容（V1.0/V1.1）。"""
    if sensitive_info_requested:
        return True, "商家要求敏感信息（信用卡/护照）"
    if user_constraint_violated:
        return True, "用户预设硬约束被违反"
    if round_count >= MAX_NEGOTIATION_ROUNDS:
        return True, f"已协商 {round_count} 轮超过上限 {MAX_NEGOTIATION_ROUNDS} 轮"
    if price_change_pct is not None and price_change_pct > 20:
        return True, f"加价 {price_change_pct:.0f}% 超酒店场景阈值 20%"
    if price_change_abs is not None and price_change_abs > 280:
        return True, f"加价 ¥{price_change_abs:.0f} 超酒店场景阈值 ¥280"
    return False, ""


def next_state(current: OrderState, trigger: str) -> OrderState | None:
    for t in TRANSITIONS:
        if t.from_state == current and t.trigger == trigger:
            return t.to_state
    return None

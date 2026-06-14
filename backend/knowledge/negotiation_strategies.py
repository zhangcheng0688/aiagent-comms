"""让步策略库：6 种 AI 主动议价策略。

每种策略定义：
- id: 唯一标识
- name: 人类可读名
- description: 何时触发
- template: 多语种话术模板（按 lang 取）
- success_signals: 商家回复中能判定"成功"的关键词（任一命中）
- failure_signals: 商家回复中能判定"失败"的关键词
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Strategy:
    id: str
    name: str
    description: str
    templates: Dict[str, str]  # lang -> text
    success_signals: Dict[str, List[str]] = field(default_factory=dict)
    failure_signals: Dict[str, List[str]] = field(default_factory=dict)
    # 是否需要"用户约束"中包含某些关键词才能触发
    requires_constraint: Optional[str] = None  # 约束文本中需包含该字符串
    # 适用场景（None 表示全场景）
    scenarios: Optional[List[str]] = None


# === 6 种策略 ===

STRATEGY_HOLD = Strategy(
    id="hold_position",
    name="坚持原条件",
    description="用户硬约束 + 商家提加价时：礼貌但坚定地重申不突破约束",
    templates={
        "ja": "恐れ入りますが、当初のプランで {budget} の予算内で考えております。{constraint} という条件がございますので、お値引きまたは代替案をいただけますでしょうか。",
        "ko": "죄송하지만, 원래 플랜 {budget} 예산 내에서 생각하고 있습니다. {constraint} 조건이 있어, 할인 또는 대안을 부탁드릴 수 있을까요?",
        "en": "I appreciate the offer, but my budget for this is {budget}. I have a {constraint} constraint—would there be any room for a discount or alternative?",
    },
    success_signals={
        "ja": ["お値引き", "割引", "代替", "検討"],
        "ko": ["할인", "대안", "검토"],
        "en": ["discount", "alternative", "consider", "reduce", "compromise"],
    },
    failure_signals={
        "ja": ["無理", "できない", "申し訳ございません"],
        "ko": ["불가능", "죄송합니다", "안 됩니다"],
        "en": ["can't", "cannot", "unable", "no way", "impossible", "not possible"],
    },
)


STRATEGY_ALT_DATE = Strategy(
    id="alt_date",
    name="替代日期",
    description="日期冲突时：商家某日无房时，AI 自动提相邻日期让步",
    templates={
        "ja": "{original_date} 以外で、{alt_dates} のいずれかであれば対応可能でしょうか。最後の手段として、1 週間前後は柔軟に調整できます。",
        "ko": "{original_date} 외에, {alt_dates} 중 하나라도 가능할까요? 최후 수단으로 일주일 전후는 유연하게 조정 가능합니다.",
        "en": "If {original_date} doesn't work, would any of these dates work: {alt_dates}? I can flex up to a week on either side as a last resort.",
    },
    success_signals={
        "ja": ["大丈夫", "可能です", "ご利用いただけます", "空室あり"],
        "ko": ["가능", "있습니다", "이용 가능"],
        "en": ["available", "works", "can do", "we have", "yes"],
    },
    failure_signals={
        "ja": ["全日満室", "全期間", "どの日も"],
        "ko": ["모든 날", "전부 만석"],
        "en": ["all sold out", "all booked", "no availability"],
    },
    scenarios=None,  # 全场景适用（酒店/租车/机票都涉及日期）
)


STRATEGY_VALUE_TRADE = Strategy(
    id="value_trade",
    name="增值让步",
    description="AI 提出加订增值服务（如早餐/晚餐/接送）换取价格不变或小幅下降",
    templates={
        "ja": "お部屋の条件はそのままで結構です。もし可能であれば、{value_added}（追加 {price}）をお付けいただけますか。総合的なご検討をお願いします。",
        "ko": "객실 조건은 그대로 괜찮습니다. 가능하시다면, {value_added} (추가 {price}) 를 추가해 주실 수 있을까요? 종합적으로 검토 부탁드립니다.",
        "en": "The room conditions can stay as-is. Could we add {value_added} (an extra {price}) as compensation? I think that's a fair overall trade.",
    },
    success_signals={
        "ja": ["可能です", "ご利用いただけます", "追加できます"],
        "ko": ["가능", "추가 가능", "있습니다"],
        "en": ["can do", "possible", "we can add", "we'll add"],
    },
    failure_signals={
        "ja": ["プランに含む", "セットのみ", "変更不可"],
        "ko": ["포함", "변경 불가", "세트만"],
        "en": ["set only", "can't change", "not modifiable"],
    },
)


STRATEGY_CHAIN_OFFER = Strategy(
    id="chain_offer",
    name="链式反提案",
    description="商家提加价后，AI 反提案用多项需求打包换取商家让步（如'我加订 3 晚 + 接送 + 早餐'换不加价）",
    templates={
        "ja": "おっしゃる追加料金 {price} についてですが、もし {bundle_items} のセットでお願いできるなら、合計金額はそのままで構わないかご検討いただけますか。",
        "ko": "말씀하신 추가 요금 {price} 건에 대해, 만약 {bundle_items} 세트로 부탁드릴 수 있다면 총 금액은 그대로 유지 가능할지 검토 부탁드립니다.",
        "en": "Regarding the {price} upcharge you mentioned—would you consider keeping the total unchanged if I bundle in {bundle_items}?",
    },
    success_signals={
        "ja": ["セットで可能です", "セットプラン", "おまとめできます"],
        "ko": ["세트 가능", "묶음 가능", "세트로"],
        "en": ["bundle works", "package deal", "we can do that", "set price"],
    },
    failure_signals={
        "ja": ["セット不可", "別会計", "別々で"],
        "ko": ["세트 불가", "별도", "개별"],
        "en": ["can't bundle", "separate", "different"],
    },
    scenarios=None,  # 全场景
)


STRATEGY_LOYALTY = Strategy(
    id="loyalty",
    name="忠诚度换价",
    description="AI 表明是回头客/忠诚客户，请求会员价或长租折扣",
    templates={
        "ja": "私、[company] のリピート客でございます。年間 {stays} 回程度ご利用しております。loyalty program のご優待はございますか。",
        "ko": "저는 {company} 단골 고객입니다. 연간 {stays} 회 정도 이용하고 있습니다. 멤버십 할인이 있나요?",
        "en": "I should mention I'm a repeat customer at {company}—I stay with you {stays} times a year on average. Do you have a loyalty program I could apply to?",
    },
    success_signals={
        "ja": ["メンバー", "会員", "リピーター", "割引"],
        "ko": ["멤버", "회원", "단골", "할인"],
        "en": ["member", "loyalty", "discount", "rewards", "VIP"],
    },
    failure_signals={
        "ja": ["ありません", "ございません", "新規のみ"],
        "ko": ["없습니다", "신규만"],
        "en": ["no program", "first-time only", "we don't have"],
    },
    scenarios=None,
)


STRATEGY_WALK_AWAY = Strategy(
    id="walk_away",
    name="提前离场",
    description="协商到第 N 轮仍无突破时，AI 主动提出终止沟通，避免无限拉锯",
    templates={
        "ja": "複数回のご相談にも関わらず、申し訳ございませんが、{constraint} のため今回は見送らせていただきます。お忙しいところ失礼いたしました。",
        "ko": "여러 차례 상담에도 불구하고 죄송합니다만, {constraint} 때문에 이번에는 진행하지 않겠습니다. 바쁘신 중에 실례했습니다.",
        "en": "I appreciate your patience, but given the {constraint}, I won't be able to proceed this time. Thank you for your time.",
    },
    success_signals={},  # 此策略不期望成功
    failure_signals={},
    scenarios=None,
)


ALL_STRATEGIES: List[Strategy] = [
    STRATEGY_HOLD,
    STRATEGY_ALT_DATE,
    STRATEGY_VALUE_TRADE,
    STRATEGY_CHAIN_OFFER,
    STRATEGY_LOYALTY,
    STRATEGY_WALK_AWAY,
]

STRATEGY_BY_ID = {s.id: s for s in ALL_STRATEGIES}


# === 场景化升级阈值（V1.2 新增） ===
SCENARIO_ESCALATION_THRESHOLDS = {
    "hotel": {"price_change_pct": 20, "price_change_abs": 280},
    "car_rental": {"price_change_pct": 30, "price_change_abs": 240},
    "flight": {"price_change_pct": 25, "price_change_abs": 30000},  # 机票按 ¥ 而非 ¥/晚
}


# === 协商上限 ===
# 1.7.1 升级到 20 轮支持 10 分钟长沟通；与 backend.config 同步
MAX_NEGOTIATION_ROUNDS = 20

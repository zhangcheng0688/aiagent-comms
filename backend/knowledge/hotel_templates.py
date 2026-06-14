"""酒店场景话术模板（开场/确认/协商/结束）+ 兜底话术。"""
from __future__ import annotations

# 商务敬语规则（按语种）
HONORIFIC_RULES = {
    "ja": {
        "open": "私、[ユーザー名]と申します。[ホテル名]の予約についてお問い合わせがあり、お電話いたしました。恐れ入りますが、フロントご担当者様をお願いできますでしょうか。",
        "confirm": "恐れ入りますが、[item]について確認をお願いできますでしょうか。",
        "negotiate": "ご希望に沿えるよう調整可能でしょうか。代替案などございましたら、お知らせいただけますと幸いです。",
        "close_success": "ご確認いただき、誠にありがとうございました。[summary]について承知いたしました。",
        "close_failure": "ご希望に添えず申し訳ございません。今回は見送らせていただきます。お忙しいところ失礼いたしました。",
        "fallback_understand": "恐れ入りますが、もう一度おっしゃっていただけますでしょうか。",
        "fallback_silence": "もしもし、聞こえますでしょうか。",
        "fallback_denial": "かしこまりました。今回は見送らせていただきます。失礼いたします。",
    },
    "ko": {
        "open": "안녕하세요. [사용자명]이라고 합니다. [호텔명] 예약 관련하여 문의드리고 싶어 전화드렸습니다. 프론트 담당자와 통화 가능할까요?",
        "confirm": "죄송하지만, [item]에 대해 확인 부탁드려도 될까요?",
        "negotiate": "원하시는 조건에 맞출 수 있도록 조정이 가능할까요? 대안方案이 있으시면 알려주시면 감사하겠습니다.",
        "close_success": "확인해 주셔서 감사합니다. [summary]에 대해承知했습니다.",
        "close_failure": "원하시는 바에 부합하지 못해 죄송합니다. 이번에는 패스하도록 하겠습니다. 바쁘신 중에 실례했습니다.",
        "fallback_understand": "죄송하지만, 다시 한 번 말씀해 주실 수 있을까요?",
        "fallback_silence": "여보세요, 들리시나요?",
        "fallback_denial": "알겠습니다. 이번에는 패스하도록 하겠습니다. 실례했습니다.",
    },
    "en": {
        "open": "Good [morning/afternoon/evening], this is [user_name] calling on behalf of a customer. May I speak with the front desk regarding a reservation at [hotel_name]?",
        "confirm": "Could you please confirm [item] for me?",
        "negotiate": "Is there any flexibility on that, or perhaps an alternative arrangement we could consider?",
        "close_success": "Thank you for confirming. I have noted [summary] for our records. We appreciate your help.",
        "close_failure": "I understand that won't work. We will not proceed this time. Thank you for your time.",
        "fallback_understand": "I apologize, could you please repeat that?",
        "fallback_silence": "Hello, are you still there?",
        "fallback_denial": "Understood, we will not proceed. Thank you for your time.",
    },
}

# 酒店场景变量替换示例
VARIABLE_REPLACEMENTS = {
    "[user_name]": {"ja": "山田", "ko": "김", "en": "Alex"},
    "[hotel_name]": {"ja": "ホテル", "ko": "호텔", "en": "the property"},
    "[item]": {"ja": "ご予約内容", "ko": "예약 내용", "en": "the reservation details"},
    "[summary]": {"ja": "ご予約内容", "ko": "요약", "en": "the summary"},
}


def get_template(scene: str, lang: str = "en", **vars) -> str:
    """获取场景模板，自动替换变量。"""
    rules = HONORIFIC_RULES.get(lang, HONORIFIC_RULES["en"])
    tmpl = rules.get(scene, rules["fallback_understand"])
    for k, v in vars.items():
        tmpl = tmpl.replace(f"[{k}]", v)
    return tmpl

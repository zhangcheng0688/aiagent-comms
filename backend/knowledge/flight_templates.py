"""机票场景话术模板（V1.1）。"""
from __future__ import annotations

HONORIFIC_RULES = {
    "ja": {
        "open": "お世話になります。私、[ユーザー名]と申します。ANA/[会社名]の予約についてお問い合わせがあり、お電話いたしました。",
        "ivr_hint": "日本語で対応可能でしょうか。または、英語の担当者をお繋ぎいただけますでしょうか。",
        "confirm": "恐れ入りますが、[item]についてご確認をお願いできますでしょうか。",
        "negotiate": "いくつか確認させてください。[question]",
        "close_success": "ご確認いただき、誠にありがとうございました。最終内容をまとめます：[summary]",
        "close_failure": "ご希望に沿えず申し訳ございません。今回は見送らせていただきます。お忙しいところ失礼いたしました。",
        "fallback_understand": "恐れ入りますが、もう一度おっしゃっていただけますでしょうか。",
        "fallback_silence": "もしもし、聞こえますでしょうか。",
        "fallback_denial": "かしこまりました。今回は見送らせていただきます。失礼いたします。",
    },
    "ko": {
        "open": "안녕하세요. [사용자명]입니다. ANA/[항공사] 예약 관련하여 문의드리고 싶어 전화드렸습니다.",
        "ivr_hint": "한국어 상담원 또는 영어 상담원 연결 부탁드립니다.",
        "confirm": "죄송하지만, [item]에 대해 확인 부탁드려도 될까요?",
        "negotiate": "몇 가지 확인하겠습니다. [question]",
        "close_success": "확인해 주셔서 감사합니다. 최종 내용을 정리하겠습니다: [summary]",
        "close_failure": "원하시는 바에 부합하지 못해 죄송합니다. 이번에는 패스하도록 하겠습니다.",
        "fallback_understand": "죄송하지만, 다시 한 번 말씀해 주실 수 있을까요?",
        "fallback_silence": "여보세요, 들리시나요?",
        "fallback_denial": "알겠습니다. 이번에는 패스하도록 하겠습니다.",
    },
    "en": {
        "open": "Good [morning/afternoon/evening], this is [user_name] calling. I have a reservation with [company] and need to make some changes. May I speak with a customer service representative?",
        "ivr_hint": "May I please have an English-speaking agent?",
        "confirm": "Could you please confirm [item] for me?",
        "negotiate": "I have a few items to clarify. [question]",
        "close_success": "Thank you for your help. To summarize: [summary]",
        "close_failure": "I understand. We will not proceed this time. Thank you for your time.",
        "fallback_understand": "I apologize, could you please repeat that?",
        "fallback_silence": "Hello, are you still there?",
        "fallback_denial": "Understood, we will not proceed. Thank you for your time.",
    },
}


def get_template(scene: str, lang: str = "en", **vars) -> str:
    rules = HONORIFIC_RULES.get(lang, HONORIFIC_RULES["en"])
    tmpl = rules.get(scene, rules["fallback_understand"])
    for k, v in vars.items():
        tmpl = tmpl.replace(f"[{k}]", v)
    return tmpl

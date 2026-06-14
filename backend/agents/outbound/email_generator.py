"""开发信生成器：LLM + cable 行业词库 + 静态模板兜底。"""
from __future__ import annotations

import json
import re
from datetime import datetime

from ...domains import get_domain_loader
from ...llm_client import call_mavis_llm, extract_json_from_text
from ...models import Lead


COUNTRY_LANG = {
    "Japan": "ja",
    "South Korea": "ko",
    "Korea": "ko",
    "Germany": "de",  # 先按英语，但可扩展
    "France": "fr",
}


def detect_language(lead: Lead) -> str:
    """根据国家推测首选语言，默认英语。"""
    if lead.country:
        return COUNTRY_LANG.get(lead.country, "en")
    return "en"


FALLBACK_TEMPLATES = {
    "sample_confirm": {
        "en": {
            "subject": "Sample request: {company_name} / XLPE cable inquiry",
            "body": """Dear {contact_name},

I hope this email finds you well. We are a leading cable manufacturer in China, specializing in XLPE insulated power cables, LSZH flame-retardant cables, and IEC/GB certified products.

I noticed {company_name} is active in the {country} market. We would love to support your projects with competitive pricing and stable delivery.

Would you be interested in receiving a 1.5m sample of our XLPE 4mm² cable for lab testing? We can confirm freight terms and delivery schedule upon your reply.

Looking forward to hearing from you.

Best regards,
AI Cable Sales Assistant
""",
        },
        "ja": {
            "subject": "サンプル提供のご提案 - {company_name}",
            "body": """{contact_name} 様

初めまして。中国のケーブルメーカーで、XLPE 絶縁電力ケーブル、低煙無ハロゲン難燃ケーブル、IEC/GB 認証製品を専門に扱っております。

{company_name} 様の {country} 市場での事業を拝見し、ぜひご支援させていただければと思い、ご連絡差し上げました。

XLPE 4mm² ケーブルのサンプル 1.5m を試験用にご提供可能でしょうか。運賃条件と納期につきましても、ご返信をいただければ確認いたします。

ご検討のほど、よろしくお願いいたします。

AI Cable Sales Assistant
""",
        },
        "ko": {
            "subject": "샘플 제공 제안 - {company_name}",
            "body": """{contact_name} 님

안녕하세요. 중국의 케이블 제조사로 XLPE 절연 전력 케이블, 저연무할로겐 난연 케이블, IEC/GB 인증 제품을 전문으로 하고 있습니다.

{company_name} 님의 {country} 시장 사업을 보고 지원드리고 싶어 연락드립니다.

XLPE 4mm² 케이블 샘플 1.5m 를 시험용으로 제공드릴 수 있을까요? 운임 조건과 납기는 회신 주시면 확인드리겠습니다.

검토 부탁드립니다.

AI Cable Sales Assistant
""",
        },
    },
    "price_negotiation": {
        "en": {
            "subject": "Volume pricing for {company_name} - cable partnership",
            "body": """Dear {contact_name},

I hope you are doing well. We supply XLPE power cables, armored cables, and LSZH products to distributors and EPC contractors worldwide.

Given {company_name}'s scale in {country}, we would like to discuss a volume-based partnership. For annual volumes above 500,000 meters, we can offer competitive pricing with flexible payment terms.

Could we schedule a short call or email exchange to understand your target specs and volume?

Best regards,
AI Cable Sales Assistant
""",
        },
        "ja": {
            "subject": "{company_name} 様向け 大口価格のご提案",
            "body": """{contact_name} 様

平素より大変お世話になっております。中国のケーブルメーカーで、XLPE 電力ケーブル、鎧装ケーブル、低煙無ハロゲン製品を全世界のディストリビューター・EPC 向けに供給しております。

{company_name} 様の {country} における規模を拝見し、年間 50 万メートル以上の大口契約に応じた価格と柔軟な支払条件をご提案させていただきたく存じます。

目標仕様と数量をお聞かせいただけますでしょうか。

AI Cable Sales Assistant
""",
        },
        "ko": {
            "subject": "{company_name} 대량 구매 가격 제안",
            "body": """{contact_name} 님

안녕하세요. XLPE 전력 케이블, 장갑 케이블, 저연무할로겐 제품을 전 세계 유통사와 EPC 계약자에게 공급하는 중국 케이블 제조사입니다.

{company_name} 님의 {country} 시장 규모를 고려할 때, 연간 50만 미터 이상의 대량 계약에 대해 경쟁력 있는 가격과 유연한 지급 조건을 제안드리고 싶습니다.

목표 사양과 수량을 알려주시면 검토 후 회신드리겠습니다.

AI Cable Sales Assistant
""",
        },
    },
}


def _fallback_email(lead: Lead, scenario: str, lang: str) -> dict:
    """LLM 不可用时的静态模板兜底。"""
    templates = FALLBACK_TEMPLATES.get(scenario, FALLBACK_TEMPLATES["sample_confirm"])
    tmpl = templates.get(lang, templates["en"])
    ctx = {
        "contact_name": lead.contact_name or "Sir/Madam",
        "company_name": lead.company_name,
        "country": lead.country or "your",
    }
    return {
        "subject": tmpl["subject"].format(**ctx),
        "body": tmpl["body"].format(**ctx),
        "language": lang,
        "mode": "template",
    }


async def generate_outreach_email(lead: Lead, scenario: str | None = None) -> dict:
    """为指定线索生成一封开发信。

    返回 {"subject": str, "body": str, "language": str, "mode": "llm"|"template"}
    """
    lang = detect_language(lead)
    sc = scenario or lead.scenario or "sample_confirm"

    loader = get_domain_loader()
    injection = loader.build_prompt_injection("cable", sc, lang)
    phrase = loader.get_phrasebook("cable", sc, lang)
    phrase_hint = "\n".join(f'- "{p}"' for p in phrase[:3])

    system = f"""You are a professional B2B cable sales assistant. Write a concise, polite cold outreach email for a potential overseas buyer.

Rules:
1. Output ONLY a JSON object with keys: subject, body, language.
2. The body should be 120-180 words, single paragraph or short paragraphs.
3. Mention the recipient's company name naturally.
4. Use the cable industry context below to sound authentic.
5. Do not use markdown code blocks in the output.

{injection}

Example phrases in {lang}:
{phrase_hint}
"""

    user = f"""Lead info:
- Company: {lead.company_name}
- Contact: {lead.contact_name or 'unknown'}
- Country: {lead.country or 'unknown'}
- Scenario: {sc}
- Target language: {lang}

Write the outreach email now."""

    content = await call_mavis_llm(system=system, user=user, temperature=0.5, max_tokens=800)
    data = extract_json_from_text(content or "")
    if isinstance(data, dict) and data.get("subject") and data.get("body"):
        return {
            "subject": str(data["subject"]).strip(),
            "body": str(data["body"]).strip(),
            "language": str(data.get("language", lang)),
            "mode": "llm",
        }

    return _fallback_email(lead, sc, lang)

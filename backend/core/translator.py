"""翻译层抽象：DeepL → 通用 API → 大模型兜底。"""
from __future__ import annotations
import httpx
import re
from ..config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL, DEEPL_API_KEY, TRANSLATION_PROVIDER

LANG_CODE = {
    "en": "EN-US",
    "ja": "JA",
    "ko": "KO",
    "zh": "ZH",
    "th": "TH",
}


async def translate(text: str, target: str, source: str = "zh") -> str:
    """异步翻译接口。target 是目标语种代码 (en/ja/ko)。"""
    if not text or target == "zh" or target == source:
        return text

    # 1. 尝试 DeepL
    if TRANSLATION_PROVIDER == "deepl" and DEEPL_API_KEY:
        try:
            return await _translate_deepl(text, target, source)
        except Exception:
            pass

    # 2. 兜底：大模型直出
    return await _translate_llm(text, target, source)


async def _translate_deepl(text: str, target: str, source: str) -> str:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api-free.deepl.com/v2/translate",
            headers={"Authorization": f"DeepL-Auth-Key {DEEPL_API_KEY}"},
            data={
                "text": text,
                "source_lang": LANG_CODE.get(source, "ZH").upper(),
                "target_lang": LANG_CODE.get(target, "EN-US").upper(),
            },
        )
        resp.raise_for_status()
        return resp.json()["translations"][0]["text"]


async def _translate_llm(text: str, target: str, source: str) -> str:
    """用大模型做翻译。带商务敬语规则。"""
    honorific_rules = {
        "ja": "使用 です/ます 体，避免简体。可用 お/ご 前缀。称呼对方用 そちら/フロント 様。",
        "ko": "使用 합쇼체/해요体。称呼对方用 ~님 或 ~께서。",
        "en": "Use formal hotel-customer-service English. Address as 'you' or 'the property'. Avoid contractions.",
    }
    rule = honorific_rules.get(target, "")
    system = f"""You are a professional hotel-customer-service translator.
Source language: {source}. Target language: {target}.
{rule}
Only return the translated text, no explanations, no quotes."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{LLM_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            out = resp.json()["choices"][0]["message"]["content"].strip()
            return _strip_quotes(out)
    except Exception:
        return text  # 终极兜底：原文


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    return s

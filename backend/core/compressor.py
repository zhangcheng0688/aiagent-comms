"""1.7.3 上下文摘要压缩器。

长对话（10+ 分钟 ≈ 20+ 轮）会塞爆 LLM context window + 烧钱。
策略：每 N 轮触发一次"摘要压缩"，把旧 N 轮压成 1 段 summary，
注入到下一轮 LLM 的 context 头部，下游 LLM 看的是：
  - 摘要（早期）
  - 最近 8 轮原文（晚期）
两段拼起来当 context。
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
from typing import List

import httpx

from ..config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL

log = logging.getLogger("aiagent.compress")


async def compress_dialogue(dialogue: list[dict], scenario: str = "hotel") -> str:
    """把早期 N 轮对话压缩成 1 段摘要。

    dialogue: [{speaker, original, translated, ...}, ...]
    返回：1 段中文摘要（300-500 字），保留关键事实。
    """
    if len(dialogue) < 5:
        return ""  # 太短不用压

    # 构造输入
    lines = []
    for t in dialogue:
        speaker = "AI" if t.get("speaker") == "ai" else "商家"
        text = t.get("translated") or t.get("original", "")
        if text:
            lines.append(f"[{speaker}] {text[:200]}")
    raw = "\n".join(lines)
    if len(raw) < 200:
        return ""

    # 启发式 fallback（无 LLM 时）
    if not (LLM_API_KEY and LLM_API_KEY != "sk-xxx") and not os.getenv("MAVIS_ACCESS_TOKEN"):
        return _heuristic_compress(dialogue, scenario)

    # 调 LLM 压缩
    try:
        return await _llm_compress(raw, scenario)
    except Exception as e:
        log.warning(f"llm compress failed, fall back heuristic: {e}")
        return _heuristic_compress(dialogue, scenario)


async def _llm_compress(raw_text: str, scenario: str) -> str:
    """调 M3 压缩对话。"""
    prompt = f"""你是一个外贸助理 AI 的"对话压缩器"。把下面这段冗长的电话/短信沟通历史压缩成 200-300 字中文摘要。

要求：
1. 保留关键事实：商家名、报价、关键诉求、约束
2. 用第三人称（"客户"指客户，"AI"指自己，"商家"指对方）
3. 突出"哪些已经谈妥、哪些还在争、商家态度如何"
4. 不复述废话（"好的"、"嗯"、"OK"）
5. 用陈述句，避免问句

场景：{scenario}

对话历史：
{raw_text}

压缩后的摘要："""
    # 直接调 LLM（复用已有 llm_client）
    import httpx
    headers = {"Content-Type": "application/json"}
    if os.getenv("MAVIS_ACCESS_TOKEN"):
        headers["Token"] = os.environ["MAVIS_ACCESS_TOKEN"]
    elif LLM_API_KEY and LLM_API_KEY != "sk-xxx":
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    body = {
        "model": LLM_MODEL,
        "max_tokens": 400,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{LLM_API_BASE}/messages", headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
            return data["content"][0]["text"].strip()
    except Exception:
        # 退路：OpenAI 兼容格式
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{LLM_API_BASE}/chat/completions", headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()


def _heuristic_compress(dialogue: list[dict], scenario: str) -> str:
    """无 LLM 时的启发式压缩：提取商家名/价格/关键词。"""
    full_text = " ".join(t.get("original", "") for t in dialogue)
    # 商家名 = 第一个 AI turn 提到的酒店/工厂名（粗略）
    orgs = re.findall(r"([一-龥]{2,15}(?:酒店|宾馆|工厂|公司|集团|店))", full_text)
    org = orgs[0] if orgs else "商家"
    # 价格/加价
    prices = re.findall(r"([+\-]?[¥$€£]?\s*\d[\d,]*\.?\d*)\s*(?:元|RMB|美元|USD)?", full_text)
    prices_str = "、".join(prices[:5]) if prices else "（无具体数字）"
    # 商家态度
    positive = sum(1 for t in dialogue if t.get("speaker") != "ai" and any(
        kw in t.get("original", "").lower()
        for kw in ["yes", "ok", "sure", "confirm", "好的", "可以", "没问题", "当然"]
    ))
    negative = sum(1 for t in dialogue if t.get("speaker") != "ai" and any(
        kw in t.get("original", "").lower()
        for kw in ["no", "cannot", "refuse", "不行", "不可以", "拒绝", "不可能"]
    ))
    attitude = "配合" if positive > negative else ("抗拒" if negative > positive else "中立")

    return (
        f"[摘要] 客户委托 AI 与{org}沟通（场景：{scenario}）。"
        f"目前已谈到第 {len(dialogue)} 轮，"
        f"涉及价格/条款：{prices_str}。"
        f"商家态度：{attitude}（正面 {positive} 次 / 负面 {negative} 次）。"
        f"后续需继续往客户目标推进。"
    )


def split_for_context(
    dialogue: list[dict],
    summary: str,
    keep_recent: int = 8,
) -> tuple[str, list[dict]]:
    """把 dialogue 切成 (早期摘要, 近期原文)。

    返回:
        summary: 早期 N 轮的摘要（可能为空）
        recent:  最近 keep_recent 轮的原文 list
    """
    if len(dialogue) <= keep_recent:
        return "", dialogue
    early = dialogue[:-keep_recent]
    recent = dialogue[-keep_recent:]
    return summary, recent

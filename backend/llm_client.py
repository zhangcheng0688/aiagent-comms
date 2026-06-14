"""Mavis 托管 LLM 客户端：Anthropic Messages 格式。

Mavis daemon 在 opencode-plugin 里给 managed hosts 注入 `Token: <MAVIS_ACCESS_TOKEN>` 头，
endpoint 是 `/mavis/api/v1/llm/v1/messages`（Anthropic 风格，不是 OpenAI 风格）。
我们直接复用同样的鉴权，但用 Python 调，绕过 opencode。

优点：V2.0 跑通 LLM 真决策，不依赖 mock。
"""
from __future__ import annotations
import os
import json
import re
import httpx

# 复用 daemon 的 endpoint
DEFAULT_BASE = "https://agent.minimaxi.com/mavis/api/v1/llm/v1"
DEFAULT_MODEL = "MiniMax-M3"

# env: LLM_API_BASE / LLM_API_KEY / LLM_MODEL
# - 设了 LLM_API_KEY：用之（生产路径）
# - 没设：用 MAVIS_ACCESS_TOKEN（Mavis 进程内）
# - 都没有：返回 None（降级 V1.2）

TOKEN_RE = re.compile(r"^```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.MULTILINE)


def _get_token() -> str | None:
    """从多种来源拿 token。"""
    explicit = os.getenv("LLM_API_KEY", "").strip()
    if explicit and explicit != "sk-xxx":
        return explicit
    mavis_tok = os.getenv("MAVIS_ACCESS_TOKEN", "").strip()
    if mavis_tok:
        return mavis_tok
    return None


async def call_mavis_llm(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.4,
) -> str | None:
    """调真 Mavis 托管 LLM。返回 content 文本，失败返回 None。"""
    token = _get_token()
    if not token:
        return None

    base = os.getenv("LLM_API_BASE", DEFAULT_BASE)
    model_id = model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    # 去掉 minimax/ 前缀（Mavis endpoint 直接用 MiniMax-M3）
    if model_id.startswith("minimax/"):
        model_id = model_id[len("minimax/"):]

    payload = {
        "model": model_id,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }

    headers = {
        "Content-Type": "application/json",
        "Token": token,
        "X-Mavis-Agent-Id": "aiagent-comms-v2",
        "User-Agent": "MiniMaxAgent",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.post(f"{base}/messages", headers=headers, json=payload)
        if r.status_code != 200:
            # 调试信息
            print(f"[mavis_llm] non-200: {r.status_code} {r.text[:200]}")
            return None
        data = r.json()
        # Anthropic 风格响应
        content = data.get("content", [])
        text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
        return "\n".join(text_parts).strip() or None
    except Exception as e:
        print(f"[mavis_llm] error: {e}")
        return None


def extract_json_from_text(text: str) -> dict | None:
    """从 LLM 文本里抠 JSON。容忍 markdown 包裹。"""
    if not text:
        return None
    # 先试纯 JSON
    try:
        return json.loads(text)
    except Exception:
        pass
    # 再试 ```json ... ```
    m = TOKEN_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 兜底：找第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return None

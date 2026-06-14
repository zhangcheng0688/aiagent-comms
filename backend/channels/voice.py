"""VOIP 渠道抽象：mock 模式 + Twilio 真实接入（方案 A：<Say>+<Gather> 同步轮询）。"""
from __future__ import annotations
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict
from ..config import (
    VOICE_MOCK,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, TWILIO_WEBHOOK_BASE,
)
from ..models import DialogueTurn

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "voice_calls.log"

# Twilio 通话的运行态缓存（call_sid -> {turn, dialogue_so_far, ev, completed, merchant_text}）
_TWILIO_CALL_STATE: Dict[str, dict] = {}


class VoiceChannel:
    """VOIP 渠道抽象。"""

    def __init__(self, mock: bool = VOICE_MOCK):
        self.mock = mock
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not LOG_PATH.exists():
            LOG_PATH.touch()

    async def call(self, to_number: str, ai_speech: str, lang: str) -> str:
        """发起 VOIP 外呼并等待商家一次回复（返回商家原话）。"""
        if self.mock:
            return await self._mock_call(to_number, ai_speech, lang)
        return await self._twilio_call(to_number, ai_speech, lang)

    async def _mock_call(self, to_number: str, ai_speech: str, lang: str) -> str:
        await asyncio.sleep(0.3)
        from .mock_merchant import generate_mock_reply
        scenario = _infer_scenario_from_log(to_number)
        merchant_reply = generate_mock_reply(ai_speech, lang, scenario)
        self._log_call(to_number, ai_speech, merchant_reply, lang, scenario)
        return merchant_reply

    async def _twilio_call(self, to_number: str, ai_speech: str, lang: str) -> str:
        """Twilio 真实外呼。

        方案 A 简化版：
        1. 第一次调用：发起外呼，传 TwiML 让 Twilio 播 ai_speech + Gather 商家回复
        2. 异步等商家说完（webhook 写入 _TWILIO_CALL_STATE[call_sid]）
        3. 返回商家原话

        这种实现意味着 DialogueEngine 一次只会触发一个 _twilio_call，等返回后再发下一句。
        Twilio 会自动根据 gather action 跳到下个 webhook。
        """
        from twilio.rest import Client
        from twilio.twiml.voice_response import VoiceResponse

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        # 构造 TwiML
        resp = VoiceResponse()
        # 选定 Twilio TTS 声音（按语种）
        voice_map = {"ja": "alice", "ko": "alice", "en": "alice"}
        chosen_voice = voice_map.get(lang, "alice")

        # 先播 AI 的话
        resp.say(ai_speech, voice=chosen_voice, language=lang)

        # 收集商家回复（最多 5 秒，POST 到我们 webhook）
        gather = resp.gather(
            input_="speech",
            language=lang,
            timeout=5,
            action=f"{TWILIO_WEBHOOK_BASE}/webhooks/twilio/gather",
            method="POST",
        )
        # 兜底：如果商家不说话，回 fallback
        resp.say(self._fallback_for_lang(lang), voice=chosen_voice, language=lang)
        resp.hangup()

        twiml = str(resp)
        webhook_url = f"{TWILIO_WEBHOOK_BASE}/webhooks/twilio/init?ai_speech={ai_speech[:100]}&to={to_number}&lang={lang}"
        # 实际发起外呼：call 落地方向是 to_number，Twilio 会拉 webhook_url 拿 TwiML
        call = client.calls.create(
            to=to_number,
            from_=TWILIO_FROM_NUMBER,
            url=webhook_url,  # 第一次 TwiML 拉取
            twiml=twiml,
        )

        # 等商家回复（webhook 写入 _TWILIO_CALL_STATE[call.sid]）
        ev = asyncio.Event()
        _TWILIO_CALL_STATE[call.sid] = {
            "turn": 1,
            "merchant_text": "",
            "ev": ev,
            "completed": False,
        }
        try:
            await asyncio.wait_for(ev.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            _TWILIO_CALL_STATE.pop(call.sid, None)
            return self._fallback_for_lang(lang)

        state = _TWILIO_CALL_STATE.pop(call.sid, {})
        return state.get("merchant_text") or self._fallback_for_lang(lang)

    def _fallback_for_lang(self, lang: str) -> str:
        return {
            "ja": "恐れ入りますが、もう一度おっしゃっていただけますでしょうか。",
            "ko": "다시 한 번 말씀해 주실 수 있을까요?",
            "en": "Could you repeat that please?",
        }.get(lang, "Could you repeat that please?")

    def _log_call(self, to: str, ai: str, merchant: str, lang: str, scenario: str):
        record = {
            "ts": datetime.utcnow().isoformat(),
            "to": to, "lang": lang, "scenario": scenario,
            "ai_speech": ai, "merchant_reply": merchant,
        }
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _infer_scenario_from_log(to_number: str) -> str:
    """Mock 模式从最近的 to_number 推断场景（实际场景会传 order 进来）。"""
    # 简化：默认 hotel。可以扩展为全局状态缓存
    return "hotel"


# === Twilio webhook handlers（Twilio 端调过来） ===
def handle_twilio_gather_webhook(call_sid: str, merchant_speech: str):
    """Webhook 收到 Twilio 商家回复时调用，唤醒 _twilio_call 的等待。"""
    state = _TWILIO_CALL_STATE.get(call_sid)
    if not state:
        return
    state["merchant_text"] = merchant_speech or ""
    state["completed"] = True
    ev = state.get("ev")
    if ev:
        ev.set()

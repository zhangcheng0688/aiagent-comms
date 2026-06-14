"""短信渠道抽象：mock + 阿里云占位。"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime
from pathlib import Path
from ..config import SMS_MOCK, ALIYUN_ACCESS_KEY, ALIYUN_ACCESS_SECRET

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "sms_messages.log"


class SmsChannel:
    def __init__(self, mock: bool = SMS_MOCK):
        self.mock = mock
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not LOG_PATH.exists():
            LOG_PATH.touch()

    async def send(self, to_number: str, content: str) -> str:
        """发送短信。Mock 模式：写入日志 + 等待预设回复。"""
        if self.mock:
            return await self._mock_send(to_number, content)
        return await self._aliyun_send(to_number, content)

    async def _mock_send(self, to_number: str, content: str) -> str:
        await asyncio.sleep(0.2)
        self._log_sms(to_number, content, "outbound")
        # Mock 商家通过短信回复
        from .mock_merchant import generate_mock_reply
        reply = generate_mock_reply(content, _infer_lang(to_number))
        self._log_sms(to_number, reply, "inbound")
        return reply

    async def _aliyun_send(self, to_number: str, content: str) -> str:
        raise NotImplementedError(
            "阿里云短信接入待实现：需要 ALIYUN_ACCESS_KEY/ALIYUN_ACCESS_SECRET 和签名/模板"
        )

    def _log_sms(self, to: str, content: str, direction: str):
        record = {
            "ts": datetime.utcnow().isoformat(),
            "to": to,
            "direction": direction,
            "content": content,
        }
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _infer_lang(phone: str) -> str:
    if phone.startswith("+81"):
        return "ja"
    if phone.startswith("+82"):
        return "ko"
    return "en"

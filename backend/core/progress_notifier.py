"""1.7.4 实时进度通知器。

长沟通（10+ 分钟）下，客户不能干等。每 60s 给客户邮箱发一封"AI 仍在跑"的进度邮件：
  - 跑了多少秒
  - 当前轮数
  - AI 正在用哪个策略
  - 商家最近一次回应
  - 还需要多久（基于当前进展预测）

设计：解耦进度推送与对话循环。
  - DialogueEngine 每轮结束调 notify_progress() 一次
  - 内部用 last_sent_at 节流，避免每轮都发邮件
  - 邮件极简（不像终稿那么花哨）
"""
from __future__ import annotations
import logging
import os
import smtplib
import ssl
import time
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from ..config import PROGRESS_NOTIFY_INTERVAL

log = logging.getLogger("aiagent.progress")


class ProgressNotifier:
    """进度通知器，绑定单订单。"""

    def __init__(self, smtp_user: str, smtp_password: str, customer_email: str, order_id: str, organization: str):
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.customer_email = customer_email
        self.order_id = order_id
        self.organization = organization
        self.started_at = time.time()
        self.last_sent_at = 0.0
        self.sent_count = 0
        self._smtp: smtplib.SMTP_SSL | None = None

    def _connect_smtp(self):
        if self._smtp:
            try:
                self._smtp.noop()
                return
            except Exception:
                self._smtp = None
        ctx = ssl.create_default_context()
        self._smtp = smtplib.SMTP_SSL("smtp.qq.com", 465, context=ctx, timeout=15)
        self._smtp.login(self.smtp_user, self.smtp_password)

    def maybe_notify(
        self,
        current_round: int,
        last_strategy: str,
        last_merchant_text: str,
        state: str,
    ) -> bool:
        """如果距上次发送 ≥ PROGRESS_NOTIFY_INTERVAL 秒，发一封进度邮件。

        返回：是否发送了
        """
        now = time.time()
        if now - self.last_sent_at < PROGRESS_NOTIFY_INTERVAL:
            return False
        if self.last_sent_at == 0:
            # 第一次：起步通知，30s 后发（让客户知道开始了）
            if now - self.started_at < 30:
                return False

        elapsed = int(now - self.started_at)
        # 估算剩余：10 分钟 cap
        eta = max(0, 600 - elapsed)

        subject = f"⏳ AI 仍在沟通 · 订单 {self.order_id}"
        text = (
            f"Hi,\n\n"
            f"您委托的{self.organization}代办正在处理中，AI 仍在和商家沟通。\n\n"
            f"⏱️ 已用时：{_fmt(elapsed)}\n"
            f"🔄 当前进度：第 {current_round} 轮\n"
            f"🎯 AI 当前策略：{last_strategy or '标准流程'}\n"
            f"📞 商家最近回复：「{last_merchant_text[:80] or '（无）'}」\n"
            f"📊 状态：{state}\n"
            f"⏳ 预计还需：{_fmt(eta) if eta > 0 else '即将出结果'}\n\n"
            f"完整记录：订单 {self.order_id}\n"
            f"AI 外贸助理 · 24h 在线\n"
        )
        html = self._build_html(elapsed, current_round, last_strategy, last_merchant_text, state, eta)
        try:
            self._send(subject, text, html)
            self.last_sent_at = now
            self.sent_count += 1
            log.info(f"progress mail #{self.sent_count} sent to {self.customer_email} (round {current_round}, {elapsed}s)")
            return True
        except Exception as e:
            log.warning(f"progress mail failed: {e}")
            return False

    def _build_html(self, elapsed, current_round, last_strategy, last_merchant_text, state, eta):
        progress_pct = min(100, int(elapsed / 600 * 100))  # 10 分钟 = 100%
        last_merchant_escaped = (last_merchant_text or "").replace('"', "&quot;").replace("<", "&lt;")[:80]
        return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#0b0d12;font-family:-apple-system,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:24px;color:#e6ebf3;">
  <div style="background:#14181f;border-left:3px solid #4f8cff;padding:18px 22px;border-radius:8px;">
    <div style="font-size:14px;color:#4f8cff;font-weight:600;margin-bottom:6px;">⏳ AI 仍在沟通</div>
    <div style="font-size:18px;font-weight:600;margin-bottom:14px;">订单 {self.order_id} · {self.organization}</div>

    <div style="background:#0b0d12;height:8px;border-radius:4px;margin-bottom:14px;overflow:hidden;">
      <div style="background:linear-gradient(90deg,#4f8cff,#7c5cff);height:8px;border-radius:4px;width:{progress_pct}%;transition:width 0.3s;"></div>
    </div>
    <div style="font-size:12px;color:#8a93a6;margin-bottom:14px;">已用时 {_fmt(elapsed)} · 预计还需 {(_fmt(eta) if eta > 0 else '即将出结果')}</div>

    <table style="width:100%;font-size:13px;line-height:1.9;">
      <tr><td style="color:#8a93a6;width:35%;">当前进度</td><td><b>第 {current_round} 轮</b></td></tr>
      <tr><td style="color:#8a93a6;">AI 策略</td><td>{last_strategy or '标准流程'}</td></tr>
      <tr><td style="color:#8a93a6;">商家回应</td><td style="color:#c5cdd9;">「{last_merchant_escaped or '（无）'}」</td></tr>
      <tr><td style="color:#8a93a6;">状态</td><td>{state}</td></tr>
    </table>

    <div style="border-top:1px solid #1c2230;padding-top:14px;margin-top:18px;font-size:12px;color:#8a93a6;">
      进展有变化会再发一封邮件。最终结果出来后，会发完整 AI 处理报告。
    </div>
  </div>
</div>
</body></html>"""

    def _send(self, subject: str, text: str, html: str):
        self._connect_smtp()
        msg = EmailMessage()
        msg["From"] = f"AI 外贸助理 <{self.smtp_user}>"
        msg["To"] = self.customer_email
        msg["Subject"] = subject
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        self._smtp.send_message(msg)

    def close(self):
        if self._smtp:
            try:
                self._smtp.quit()
            except Exception:
                pass
            self._smtp = None


def _fmt(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分 {seconds % 60} 秒"
    return f"{seconds // 3600} 小时 {(seconds % 3600) // 60} 分"


def get_smtp_creds() -> tuple[str, str]:
    """从 .env 拿 SMTP 凭据。"""
    env_path = Path(".env")
    creds = {"SMTP_USER": "", "SMTP_PASSWORD": ""}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() in creds:
                    creds[k.strip()] = v.strip()
    return creds["SMTP_USER"], creds["SMTP_PASSWORD"]

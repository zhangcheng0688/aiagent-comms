"""开发信发送：优先真实 SMTP，未配置则落库为 draft。"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from typing import Literal

from ...models import Lead, LeadStatus
from ...storage_backend import storage

log = logging.getLogger("aiagent.outbound.sender")


def _smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))


def _send_real_email(to_email: str, subject: str, body_plain: str, body_html: str | None = None) -> None:
    host = os.getenv("SMTP_HOST", "smtp.qq.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_name = os.getenv("SMTP_FROM_NAME", "AI Cable Sales Assistant")

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as server:
        server.login(user, password)
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{user}>"
        msg["To"] = to_email
        msg.set_content(body_plain)
        if body_html:
            msg.add_alternative(body_html, subtype="html")
        server.send_message(msg)


async def send_outreach_email(
    lead: Lead,
    subject: str,
    body: str,
    *,
    dry_run: bool = False,
) -> dict:
    """发送或保存开发信，并更新 lead 状态。

    返回 {"sent": bool, "mode": "real"|"draft"|"mock", "error": str|None}
    """
    mode: Literal["real", "draft", "mock"] = "real"
    error: str | None = None

    if dry_run:
        mode = "mock"
        sent = True
    elif not _smtp_configured():
        mode = "draft"
        sent = False
        error = "SMTP not configured, saved as draft"
    else:
        try:
            _send_real_email(lead.email, subject, body)
            sent = True
        except Exception as e:
            log.warning(f"outbound email failed for {lead.email}: {e}")
            mode = "draft"
            sent = False
            error = str(e)

    # 更新 lead
    lead.last_email_subject = subject
    lead.last_email_body = body
    lead.last_email_sent_at = datetime.utcnow()
    lead.status = LeadStatus.CONTACTED if sent else LeadStatus.DRAFT
    lead.updated_at = datetime.utcnow()
    await storage.update_lead(lead)

    return {"sent": sent, "mode": mode, "error": error}

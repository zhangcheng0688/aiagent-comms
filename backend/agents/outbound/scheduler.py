"""Outbound Agent 调度器：批量处理新线索 + 轮询收件箱。"""
from __future__ import annotations

import logging
from datetime import datetime

from .lead_source import default_sample_source, import_leads
from .email_generator import generate_outreach_email
from .sender import send_outreach_email
from .inbound_handler import handle_inbound_email
from ...storage_backend import storage

log = logging.getLogger("aiagent.outbound.scheduler")


async def process_outbound_batch(
    limit: int = 10,
    *,
    dry_run: bool = False,
    org_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """批量给 `new` 线索生成并发送开发信。"""
    leads = await storage.list_leads(status="new", limit=limit, org_id=org_id)
    results = {"processed": 0, "sent": 0, "draft": 0, "errors": 0}
    for lead in leads:
        try:
            email = await generate_outreach_email(lead)
            result = await send_outreach_email(lead, email["subject"], email["body"], dry_run=dry_run)
            results["processed"] += 1
            if result["mode"] == "real":
                results["sent"] += 1
            elif result["mode"] == "draft":
                results["draft"] += 1
            if result.get("error"):
                results["errors"] += 1
                log.warning(f"outbound error for {lead.email}: {result['error']}")
        except Exception as e:
            results["errors"] += 1
            log.exception(f"failed to process lead {lead.id}: {e}")
    return results


async def import_sample_leads(
    *,
    org_id: str | None = None,
    user_id: str | None = None,
) -> tuple[int, int]:
    """导入包内 cable 示例线索。"""
    return await import_leads(default_sample_source(), org_id=org_id, user_id=user_id)


async def process_inbound_replies(raw_emails: list[bytes]) -> list[dict]:
    """处理一组 inbound 邮件（可由 IMAP worker 调用）。"""
    results = []
    for raw in raw_emails:
        try:
            result = await handle_inbound_email(raw)
            results.append(result)
        except Exception as e:
            log.exception(f"failed to process inbound email: {e}")
            results.append({"handled": False, "error": str(e)})
    return results

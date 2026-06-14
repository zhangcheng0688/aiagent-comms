"""线索来源抽象 + 本地 JSON 示例实现。"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ...models import Lead, LeadCreate, LeadStatus
from ...storage_backend import storage


class LeadSource(Protocol):
    """线索来源协议。"""

    async def fetch(self, limit: int = 100) -> list[LeadCreate]: ...


@dataclass
class JsonFileLeadSource:
    """从本地 JSON 读取线索（MVP 默认）。"""

    path: Path

    async def fetch(self, limit: int = 100) -> list[LeadCreate]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        items = raw if isinstance(raw, list) else []
        return [LeadCreate(**item) for item in items[:limit]]


def default_sample_source() -> JsonFileLeadSource:
    """默认使用包内 sample_cable_leads.json。"""
    here = Path(__file__).resolve().parent
    return JsonFileLeadSource(here / "sample_cable_leads.json")


async def import_leads(
    source: LeadSource,
    *,
    org_id: str | None = None,
    user_id: str | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """把线索写入 DB，按 email + org_id 去重。

    返回 (导入成功数, 跳过重复数)。
    """
    creates = await source.fetch()
    created = 0
    skipped = 0
    for c in creates:
        existing = await storage.get_lead_by_email(c.email, org_id)
        if existing:
            skipped += 1
            continue
        if dry_run:
            created += 1
            continue
        now = datetime.utcnow()
        lead = Lead(
            id=f"ld_{uuid.uuid4().hex[:8]}",
            source=c.source,
            industry=c.industry,
            company_name=c.company_name,
            contact_name=c.contact_name,
            email=c.email,
            country=c.country,
            website=c.website,
            scenario=c.scenario,
            status=LeadStatus.NEW,
            org_id=org_id,
            user_id=user_id,
            notes=c.notes,
            created_at=now,
            updated_at=now,
        )
        await storage.create_lead(lead)
        created += 1
    return created, skipped

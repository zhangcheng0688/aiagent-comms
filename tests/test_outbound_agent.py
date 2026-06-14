"""Outbound Sales Agent 回归测试。"""
from __future__ import annotations

import pytest
import httpx
from datetime import datetime

from backend.main import app
from backend.storage_backend import storage
from backend.models import Lead, LeadStatus
from backend.agents.outbound.lead_source import default_sample_source, import_leads
from backend.agents.outbound.email_generator import generate_outreach_email
from backend.agents.outbound.sender import send_outreach_email
from backend.agents.outbound.inbound_handler import handle_inbound_email


@pytest.fixture(autouse=True)
async def _init_storage():
    await storage.init()


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def sample_leads():
    created, skipped = await import_leads(default_sample_source(), dry_run=False)
    return created, skipped


async def test_import_sample_leads(sample_leads):
    created, skipped = sample_leads
    assert created == 10
    assert skipped == 0
    # 第二次导入应全部跳过（按 email 去重）
    created2, skipped2 = await import_leads(default_sample_source(), dry_run=False)
    assert created2 == 0
    assert skipped2 == 10


async def test_generate_outreach_email():
    lead = Lead(
        id="ld_test",
        company_name="Berlin Kabel GmbH",
        contact_name="Laura Müller",
        email="l.mueller@berlinkabel.example.com",
        country="Germany",
        scenario="sample_confirm",
        status=LeadStatus.NEW,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    email = await generate_outreach_email(lead)
    assert email["subject"]
    assert email["body"]
    assert "Berlin Kabel" in email["subject"] or "Berlin Kabel" in email["body"]
    assert email["mode"] in ("llm", "template")


async def test_send_outreach_email_dry_run(sample_leads):
    leads = await storage.list_leads(status="new", limit=1)
    assert leads
    lead = leads[0]
    email = await generate_outreach_email(lead)
    result = await send_outreach_email(lead, email["subject"], email["body"], dry_run=True)
    assert result["sent"] is True
    assert result["mode"] == "mock"
    updated = await storage.get_lead(lead.id)
    assert updated.status == LeadStatus.CONTACTED
    assert updated.last_email_subject == email["subject"]


async def test_simulate_reply_creates_order(sample_leads):
    leads = await storage.list_leads(status="new", limit=1)
    lead = leads[0]
    email = await generate_outreach_email(lead)
    await send_outreach_email(lead, email["subject"], email["body"], dry_run=True)

    raw = (
        f'From: "{lead.contact_name or lead.company_name}" <{lead.email}>\n'
        f'To: outbound@aiagent.example.com\n'
        f'Subject: Re: {email["subject"]}\n'
        f'Content-Type: text/plain; charset=utf-8\n\n'
        f'Please send me a sample of XLPE 4mm² cable, 1.5m for lab testing. What is the freight cost?'
    ).encode("utf-8")

    result = await handle_inbound_email(raw)
    assert result["handled"] is True
    assert result["category"] in ("qualified", "replied")
    updated = await storage.get_lead(lead.id)
    assert updated.status == LeadStatus.ORDER_CREATED
    assert updated.order_id


async def test_api_leads_funnel(client):
    await client.post("/api/leads/import")
    r = await client.get("/api/leads/funnel")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 10
    assert "by_status" in data


async def test_api_list_and_outreach(client):
    await client.post("/api/leads/import")
    r = await client.get("/api/leads?limit=5")
    assert r.status_code == 200
    leads = r.json()
    assert len(leads) >= 5

    lead_id = leads[0]["id"]
    r2 = await client.post(f"/api/leads/{lead_id}/outreach", json={"dry_run": True})
    assert r2.status_code == 200
    payload = r2.json()
    assert payload["sent"] is True
    assert payload["subject"]
    assert payload["body"]

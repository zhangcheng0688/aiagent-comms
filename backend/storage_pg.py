"""V3.0 PostgreSQL 存储后端（生产路径）。

schema 与 SQLite 一致，但用 asyncpg + 命名参数。
不替换 storage.py，按 STORAGE_BACKEND=postgres 启用。

测试无需真 PG —— 用 mock 连接。
"""
from __future__ import annotations
import os
import json
import asyncpg
import logging
from typing import Optional
from pathlib import Path
from datetime import datetime

from .config import PG_HOST, PG_PORT, PG_DB, PG_USER, PG_PASSWORD
from .models import Order, OrderState, OrderStatus, DialogueTurn, IntentSlot, Lead, LeadStatus
from .auth import Org, User, AuthToken

log = logging.getLogger("aiagent.storage.pg")


class PostgresStorage:
    """PostgreSQL 后端。schema 与 SQLite 兼容。"""

    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
        self._dsn = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"

    async def _ensure_pool(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)

    async def init(self):
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            # 标准 SQL（去掉 SQLite-only IF NOT EXISTS 的部分，PG 也支持，但用 BIGSERIAL 替代 INTEGER PRIMARY KEY）
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    organization TEXT NOT NULL,
                    contact_number TEXT NOT NULL,
                    requirement TEXT NOT NULL,
                    constraints TEXT,
                    target_language TEXT DEFAULT 'en',
                    preferred_channel TEXT DEFAULT 'sms',
                    state TEXT NOT NULL,
                    status TEXT NOT NULL,
                    intents_json JSONB NOT NULL DEFAULT '[]',
                    dialogue_json JSONB NOT NULL DEFAULT '[]',
                    result_json JSONB,
                    org_id TEXT,
                    user_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL REFERENCES orders(id),
                    options_json JSONB NOT NULL,
                    summary TEXT NOT NULL,
                    deadline_minutes INTEGER DEFAULT 30,
                    created_at TIMESTAMPTZ NOT NULL,
                    resolved_at TIMESTAMPTZ
                );
                CREATE TABLE IF NOT EXISTS orgs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    plan TEXT DEFAULT 'free',
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL REFERENCES orgs(id),
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    org_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    last_used TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
                CREATE INDEX IF NOT EXISTS idx_orders_org ON orders(org_id);
                CREATE INDEX IF NOT EXISTS idx_proposals_order ON proposals(order_id);
                CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
                CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id);

                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    source TEXT DEFAULT 'manual',
                    industry TEXT DEFAULT 'cable',
                    company_name TEXT NOT NULL,
                    contact_name TEXT,
                    email TEXT NOT NULL,
                    country TEXT,
                    website TEXT,
                    scenario TEXT DEFAULT 'sample_confirm',
                    status TEXT DEFAULT 'new',
                    last_email_subject TEXT,
                    last_email_body TEXT,
                    last_email_sent_at TIMESTAMPTZ,
                    reply_summary TEXT,
                    order_id TEXT,
                    org_id TEXT,
                    user_id TEXT,
                    notes TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
                CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
                CREATE INDEX IF NOT EXISTS idx_leads_org ON leads(org_id);
            """)
        log.info("PostgreSQL schema initialized")

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    # === 订单 ===
    async def create_order(self, order: Order) -> None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO orders (id, organization, contact_number, requirement, constraints,
                   target_language, preferred_channel, state, status, intents_json, dialogue_json,
                   result_json, org_id, user_id, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
                order.id, order.organization, order.contact_number, order.requirement,
                order.constraints, order.target_language, order.preferred_channel.value if hasattr(order.preferred_channel, "value") else order.preferred_channel,
                order.state.value if hasattr(order.state, "value") else order.state,
                order.status.value if hasattr(order.status, "value") else order.status,
                json.dumps([i.model_dump() for i in order.intents]),
                json.dumps([d.model_dump(mode="json") for d in order.dialogue]),
                json.dumps(order.result) if order.result else None,
                getattr(order, "org_id", None), getattr(order, "user_id", None),
                order.created_at, order.updated_at,
            )

    async def update_order(self, order: Order) -> None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE orders SET state=$1, status=$2, intents_json=$3, dialogue_json=$4,
                   result_json=$5, updated_at=$6 WHERE id=$7""",
                order.state.value if hasattr(order.state, "value") else order.state,
                order.status.value if hasattr(order.status, "value") else order.status,
                json.dumps([i.model_dump() for i in order.intents]),
                json.dumps([d.model_dump(mode="json") for d in order.dialogue]),
                json.dumps(order.result) if order.result else None,
                order.updated_at, order.id,
            )

    async def get_order(self, order_id: str):
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM orders WHERE id=$1", order_id)
            if not row:
                return None
            return self._row_to_order(dict(row))

    async def list_orders(self, limit: int = 50, org_id: str | None = None):
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            if org_id:
                rows = await conn.fetch(
                    "SELECT * FROM orders WHERE org_id=$1 ORDER BY created_at DESC LIMIT $2",
                    org_id, limit,
                )
            else:
                rows = await conn.fetch("SELECT * FROM orders ORDER BY created_at DESC LIMIT $1", limit)
            return [self._row_to_order(dict(r)) for r in rows]

    async def create_proposal(self, order_id: str, proposal) -> None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO proposals (proposal_id, order_id, options_json, summary, deadline_minutes, created_at) VALUES ($1,$2,$3,$4,$5,$6)",
                proposal.proposal_id, order_id,
                json.dumps(proposal.options), proposal.summary, proposal.deadline_minutes,
                datetime.utcnow(),
            )

    async def get_proposal(self, proposal_id: str):
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM proposals WHERE proposal_id=$1", proposal_id)
            return dict(row) if row else None

    # === A2 Org/User/Token ===
    async def create_org(self, org: Org) -> None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO orgs (id, name, plan, created_at) VALUES ($1,$2,$3,$4)",
                org.id, org.name, org.plan, org.created_at,
            )

    async def get_org(self, org_id: str):
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM orgs WHERE id=$1", org_id)
            if not row:
                return None
            return Org(id=row["id"], name=row["name"], plan=row["plan"], created_at=row["created_at"])

    async def create_user(self, user: User) -> None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO users (id, org_id, email, name, password_hash, password_salt, role, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                user.id, user.org_id, user.email, user.name,
                user.password_hash, user.password_salt, user.role, user.created_at,
            )

    async def get_user_by_email(self, email: str):
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE email=$1", email)
            if not row:
                return None
            return User(**dict(row))

    async def get_user(self, user_id: str):
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
            if not row:
                return None
            return User(**dict(row))

    async def create_token(self, token: AuthToken) -> None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO auth_tokens (token_hash, user_id, org_id, created_at, expires_at, last_used)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                token.token_hash, token.user_id, token.org_id,
                token.created_at, token.expires_at, token.last_used,
            )

    async def get_token(self, token_hash: str):
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM auth_tokens WHERE token_hash=$1", token_hash)
            if not row:
                return None
            return AuthToken(**dict(row))

    async def touch_token(self, token_hash: str) -> None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE auth_tokens SET last_used=$1 WHERE token_hash=$2",
                datetime.utcnow(), token_hash,
            )

    # === A4 metrics ===
    async def count_orders(self, org_id: str | None = None) -> int:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            if org_id:
                return await conn.fetchval("SELECT COUNT(*) FROM orders WHERE org_id=$1", org_id)
            return await conn.fetchval("SELECT COUNT(*) FROM orders")

    async def count_orders_by_status(self, org_id: str | None = None) -> dict:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            if org_id:
                rows = await conn.fetch(
                    "SELECT status, COUNT(*) AS n FROM orders WHERE org_id=$1 GROUP BY status",
                    org_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT status, COUNT(*) AS n FROM orders GROUP BY status"
                )
            return {r["status"]: r["n"] for r in rows}

    async def avg_evaluation_total(self, org_id: str | None = None) -> float | None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            if org_id:
                rows = await conn.fetch(
                    """SELECT result_json FROM orders
                       WHERE org_id=$1 AND result_json::text LIKE '%evaluation%'""",
                    org_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT result_json FROM orders WHERE result_json::text LIKE '%evaluation%'"
                )
            totals = []
            for r in rows:
                data = r["result_json"]
                if isinstance(data, str):
                    data = json.loads(data)
                ev = (data or {}).get("evaluation", {})
                if ev.get("total"):
                    totals.append(ev["total"])
            if not totals:
                return None
            return round(sum(totals) / len(totals), 1)

    async def count_evaluated_orders(self, org_id: str | None = None) -> int:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            if org_id:
                return await conn.fetchval(
                    "SELECT COUNT(*) FROM orders WHERE org_id=$1 AND result_json::text LIKE '%evaluation%'",
                    org_id,
                )
            return await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE result_json::text LIKE '%evaluation%'"
            )

    # === Outbound Sales Agent ===
    async def create_lead(self, lead: Lead) -> None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO leads (id, source, industry, company_name, contact_name, email,
                   country, website, scenario, status, last_email_subject, last_email_body,
                   last_email_sent_at, reply_summary, order_id, org_id, user_id, notes,
                   created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)""",
                lead.id, lead.source, lead.industry, lead.company_name, lead.contact_name,
                lead.email, lead.country, lead.website,
                lead.status.value if hasattr(lead.status, "value") else lead.status,
                lead.last_email_subject, lead.last_email_body, lead.last_email_sent_at,
                lead.reply_summary, lead.order_id, lead.org_id, lead.user_id, lead.notes,
                lead.created_at, lead.updated_at,
            )

    async def get_lead(self, lead_id: str) -> Lead | None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM leads WHERE id=$1", lead_id)
            if not row:
                return None
            return self._row_to_lead(dict(row))

    async def get_lead_by_email(self, email: str, org_id: str | None = None) -> Lead | None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            if org_id:
                row = await conn.fetchrow(
                    "SELECT * FROM leads WHERE email=$1 AND org_id=$2", email, org_id
                )
            else:
                row = await conn.fetchrow("SELECT * FROM leads WHERE email=$1", email)
            if not row:
                return None
            return self._row_to_lead(dict(row))

    async def update_lead(self, lead: Lead) -> None:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            await conn.execute(
                """UPDATE leads SET status=$1, last_email_subject=$2, last_email_body=$3,
                   last_email_sent_at=$4, reply_summary=$5, order_id=$6, notes=$7, updated_at=$8
                   WHERE id=$9""",
                lead.status.value if hasattr(lead.status, "value") else lead.status,
                lead.last_email_subject, lead.last_email_body, lead.last_email_sent_at,
                lead.reply_summary, lead.order_id, lead.notes, lead.updated_at, lead.id,
            )

    async def list_leads(
        self, status: str | None = None, limit: int = 100, org_id: str | None = None
    ) -> list[Lead]:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            where: list[str] = []
            params: list[object] = []
            idx = 1
            if status:
                where.append(f"status=${idx}")
                params.append(status)
                idx += 1
            if org_id:
                where.append(f"org_id=${idx}")
                params.append(org_id)
                idx += 1
            query = "SELECT * FROM leads"
            if where:
                query += " WHERE " + " AND ".join(where)
            query += f" ORDER BY updated_at DESC LIMIT ${idx}"
            params.append(limit)
            rows = await conn.fetch(query, *params)
            return [self._row_to_lead(dict(r)) for r in rows]

    async def count_leads_by_status(self, org_id: str | None = None) -> dict:
        await self._ensure_pool()
        async with self.pool.acquire() as conn:
            if org_id:
                rows = await conn.fetch(
                    "SELECT status, COUNT(*) AS n FROM leads WHERE org_id=$1 GROUP BY status", org_id
                )
            else:
                rows = await conn.fetch("SELECT status, COUNT(*) AS n FROM leads GROUP BY status")
            return {r["status"]: r["n"] for r in rows}

    @staticmethod
    def _row_to_lead(row: dict) -> Lead:
        return Lead(
            id=row["id"],
            source=row.get("source"),
            industry=row.get("industry"),
            company_name=row["company_name"],
            contact_name=row.get("contact_name"),
            email=row["email"],
            country=row.get("country"),
            website=row.get("website"),
            scenario=row.get("scenario"),
            status=LeadStatus(row["status"]),
            last_email_subject=row.get("last_email_subject"),
            last_email_body=row.get("last_email_body"),
            last_email_sent_at=row.get("last_email_sent_at"),
            reply_summary=row.get("reply_summary"),
            order_id=row.get("order_id"),
            org_id=row.get("org_id"),
            user_id=row.get("user_id"),
            notes=row.get("notes"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_order(row: dict) -> Order:
        return Order(
            id=row["id"],
            organization=row["organization"],
            contact_number=row["contact_number"],
            requirement=row["requirement"],
            constraints=row["constraints"],
            target_language=row["target_language"],
            preferred_channel=row["preferred_channel"],
            state=OrderState(row["state"]),
            status=OrderStatus(row["status"]),
            intents=[IntentSlot(**i) for i in (row["intents_json"] or [])],
            dialogue=[DialogueTurn(**d) for d in (row["dialogue_json"] or [])],
            result=row["result_json"],
            org_id=row.get("org_id"),
            user_id=row.get("user_id"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

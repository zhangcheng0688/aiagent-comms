"""SQLite 存储层。"""
from __future__ import annotations
import json
import aiosqlite
from datetime import datetime
from pathlib import Path
from .config import DB_PATH
from .models import Order, OrderState, OrderStatus, DialogueTurn, IntentSlot, OrderResult
from .auth import Org, User, AuthToken

SCHEMA = """
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
    intents_json TEXT NOT NULL DEFAULT '[]',
    dialogue_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT,
    org_id TEXT,
    user_id TEXT,
    user_email TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    options_json TEXT NOT NULL,
    summary TEXT NOT NULL,
    deadline_minutes INTEGER DEFAULT 30,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);
CREATE TABLE IF NOT EXISTS orgs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    plan TEXT DEFAULT 'free',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role TEXT DEFAULT 'member',
    created_at TEXT NOT NULL,
    FOREIGN KEY (org_id) REFERENCES orgs(id)
);
CREATE TABLE IF NOT EXISTS auth_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_used TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_org ON orders(org_id);
CREATE INDEX IF NOT EXISTS idx_proposals_order ON proposals(order_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id);
"""


class Storage:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            # 1.7.4 老库兼容：加 user_email 列
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN user_email TEXT")
                await db.commit()
            except Exception:
                pass  # 列已存在
            await db.commit()

    async def create_order(self, order: Order) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO orders (id, organization, contact_number, requirement, constraints,
                   target_language, preferred_channel, state, status, intents_json, dialogue_json,
                   result_json, org_id, user_id, user_email, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order.id, order.organization, order.contact_number, order.requirement,
                    order.constraints, order.target_language, order.preferred_channel.value
                    if hasattr(order.preferred_channel, "value") else order.preferred_channel,
                    order.state.value if hasattr(order.state, "value") else order.state,
                    order.status.value if hasattr(order.status, "value") else order.status,
                    json.dumps([i.model_dump() for i in order.intents], ensure_ascii=False),
                    json.dumps([d.model_dump(mode="json") for d in order.dialogue], ensure_ascii=False),
                    json.dumps(order.result, ensure_ascii=False) if order.result else None,
                    getattr(order, "org_id", None),
                    getattr(order, "user_id", None),
                    getattr(order, "user_email", None),
                    order.created_at.isoformat(), order.updated_at.isoformat(),
                ),
            )
            await db.commit()

    async def update_order(self, order: Order) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE orders SET state=?, status=?, intents_json=?, dialogue_json=?,
                   result_json=?, updated_at=? WHERE id=?""",
                (
                    order.state.value if hasattr(order.state, "value") else order.state,
                    order.status.value if hasattr(order.status, "value") else order.status,
                    json.dumps([i.model_dump() for i in order.intents], ensure_ascii=False),
                    json.dumps([d.model_dump(mode="json") for d in order.dialogue], ensure_ascii=False),
                    json.dumps(order.result, ensure_ascii=False) if order.result else None,
                    order.updated_at.isoformat(), order.id,
                ),
            )
            await db.commit()

    async def get_order(self, order_id: str) -> Order | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return self._row_to_order(row)

    async def list_orders(self, limit: int = 50, org_id: str | None = None) -> list[Order]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if org_id:
                async with db.execute(
                    "SELECT * FROM orders WHERE org_id=? ORDER BY created_at DESC LIMIT ?",
                    (org_id, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
            else:
                async with db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)) as cursor:
                    rows = await cursor.fetchall()
            return [self._row_to_order(r) for r in rows]

    # === A2: User/Org/Token ===
    async def create_org(self, org: Org) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO orgs (id, name, plan, created_at) VALUES (?, ?, ?, ?)",
                (org.id, org.name, org.plan, org.created_at.isoformat()),
            )
            await db.commit()

    async def get_org(self, org_id: str) -> Org | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM orgs WHERE id=?", (org_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                return Org(id=row["id"], name=row["name"], plan=row["plan"],
                           created_at=datetime.fromisoformat(row["created_at"]))

    async def create_user(self, user: User) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO users (id, org_id, email, name, password_hash, password_salt, role, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user.id, user.org_id, user.email, user.name, user.password_hash,
                 user.password_salt, user.role, user.created_at.isoformat()),
            )
            await db.commit()

    async def get_user_by_email(self, email: str) -> User | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE email=?", (email,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                return User(
                    id=row["id"], org_id=row["org_id"], email=row["email"], name=row["name"],
                    password_hash=row["password_hash"], password_salt=row["password_salt"],
                    role=row["role"], created_at=datetime.fromisoformat(row["created_at"]),
                )

    async def get_user(self, user_id: str) -> User | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE id=?", (user_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                return User(
                    id=row["id"], org_id=row["org_id"], email=row["email"], name=row["name"],
                    password_hash=row["password_hash"], password_salt=row["password_salt"],
                    role=row["role"], created_at=datetime.fromisoformat(row["created_at"]),
                )

    async def create_token(self, token: AuthToken) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO auth_tokens (token_hash, user_id, org_id, created_at, expires_at, last_used)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (token.token_hash, token.user_id, token.org_id,
                 token.created_at.isoformat(), token.expires_at.isoformat(),
                 token.last_used.isoformat() if token.last_used else None),
            )
            await db.commit()

    async def get_token(self, token_hash: str) -> AuthToken | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM auth_tokens WHERE token_hash=?", (token_hash,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                return AuthToken(
                    token_hash=row["token_hash"], user_id=row["user_id"], org_id=row["org_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    expires_at=datetime.fromisoformat(row["expires_at"]),
                    last_used=datetime.fromisoformat(row["last_used"]) if row["last_used"] else None,
                )

    async def touch_token(self, token_hash: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE auth_tokens SET last_used=? WHERE token_hash=?",
                (datetime.utcnow().isoformat(), token_hash),
            )
            await db.commit()

    async def count_orders(self, org_id: str | None = None) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            if org_id:
                async with db.execute("SELECT COUNT(*) FROM orders WHERE org_id=?", (org_id,)) as cur:
                    return (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM orders") as cur:
                return (await cur.fetchone())[0]

    async def count_orders_by_status(self, org_id: str | None = None) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            if org_id:
                async with db.execute(
                    "SELECT status, COUNT(*) FROM orders WHERE org_id=? GROUP BY status",
                    (org_id,),
                ) as cur:
                    rows = await cur.fetchall()
            else:
                async with db.execute(
                    "SELECT status, COUNT(*) FROM orders GROUP BY status"
                ) as cur:
                    rows = await cur.fetchall()
            return {r[0]: r[1] for r in rows}

    async def avg_evaluation_total(self, org_id: str | None = None) -> float | None:
        async with aiosqlite.connect(self.db_path) as db:
            if org_id:
                async with db.execute(
                    """SELECT result_json FROM orders
                       WHERE org_id=? AND result_json LIKE '%evaluation%'""",
                    (org_id,),
                ) as cur:
                    rows = await cur.fetchall()
            else:
                async with db.execute(
                    "SELECT result_json FROM orders WHERE result_json LIKE '%evaluation%'"
                ) as cur:
                    rows = await cur.fetchall()
            totals = []
            for r in rows:
                try:
                    data = json.loads(r[0])
                    ev = data.get("evaluation", {})
                    if ev.get("total"):
                        totals.append(ev["total"])
                except Exception:
                    pass
            if not totals:
                return None
            return round(sum(totals) / len(totals), 1)

    async def count_evaluated_orders(self, org_id: str | None = None) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            if org_id:
                async with db.execute(
                    "SELECT COUNT(*) FROM orders WHERE org_id=? AND result_json LIKE '%evaluation%'",
                    (org_id,),
                ) as cur:
                    row = await cur.fetchone()
            else:
                async with db.execute(
                    "SELECT COUNT(*) FROM orders WHERE result_json LIKE '%evaluation%'"
                ) as cur:
                    row = await cur.fetchone()
            return row[0] if row else 0

    async def create_proposal(self, order_id: str, proposal) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO proposals (proposal_id, order_id, options_json, summary, deadline_minutes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    proposal.proposal_id, order_id,
                    json.dumps(proposal.options, ensure_ascii=False),
                    proposal.summary, proposal.deadline_minutes,
                    datetime.utcnow().isoformat(),
                ),
            )
            await db.commit()

    async def get_proposal(self, proposal_id: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return dict(row)

    @staticmethod
    def _row_to_order(row) -> Order:
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
            intents=[IntentSlot(**i) for i in json.loads(row["intents_json"])],
            dialogue=[DialogueTurn(**d) for d in json.loads(row["dialogue_json"])],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            org_id=row["org_id"] if "org_id" in row.keys() else None,
            user_id=row["user_id"] if "user_id" in row.keys() else None,
            user_email=row["user_email"] if "user_email" in row.keys() else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


storage = Storage()

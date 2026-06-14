"""A2 用户/租户系统。

极简设计：
- User: email + 密码 (PBKDF2 hash) + 归属 org
- Org: 团队/公司
- Token: 随机 32 字节，DB 存 hash 后的 token (不复用明文)
- Auth: Bearer <token>，中间件从 DB 查 user_id → 注入 request.state

为什么不用 JWT：
- demo 阶段要简单，撤销 token 是刚需（用户改密码立即失效）
- 用 hash 存 token 跟密码同款逻辑，安全等级一致
"""
from __future__ import annotations
import secrets
import hashlib
import hmac
import time
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

# PBKDF2 (无第三方依赖)
def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return dk.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return hmac.compare_digest(dk.hex(), hash_hex)


def issue_token() -> tuple[str, str]:
    """返回 (raw_token, hash_hex)。raw_token 给用户，hash 存 DB。"""
    raw = secrets.token_urlsafe(32)
    h = hashlib.sha256(raw.encode()).hexdigest()
    return raw, h


def verify_token(raw_token: str, hash_hex: str) -> bool:
    h = hashlib.sha256(raw_token.encode()).hexdigest()
    return hmac.compare_digest(h, hash_hex)


# === Pydantic models ===
class Org(BaseModel):
    id: str
    name: str
    plan: str = "free"  # free / pro / enterprise
    created_at: datetime


class User(BaseModel):
    id: str
    org_id: str
    email: str
    name: str
    password_hash: str
    password_salt: str
    role: str = "member"  # admin / member
    created_at: datetime


class AuthToken(BaseModel):
    token_hash: str  # 存的是 hash
    user_id: str
    org_id: str
    created_at: datetime
    expires_at: datetime
    last_used: datetime | None = None


class RegisterRequest(BaseModel):
    org_name: str
    email: str
    password: str = Field(min_length=6)
    name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    user: dict
    org: dict
    token: str
    expires_at: datetime

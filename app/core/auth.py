"""
SentinelStream Auth Core
JWT creation/verification, password hashing, API key generation.
"""

import secrets
import string
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Passwords ──────────────────────────────────────────────
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ────────────────────────────────────────────────────
def create_access_token(subject: str, expires_minutes: int = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.JWT_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Returns subject (user_id as str) or None if invalid."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


# ── API Keys ───────────────────────────────────────────────
def generate_api_key() -> tuple[str, str, str]:
    """
    Returns (full_key, prefix, hash_of_full_key).
    full_key  — shown ONCE to user on creation e.g. sk_live_abc123...
    prefix    — stored & shown in UI          e.g. sk_live_abc1
    key_hash  — bcrypt hash stored in DB
    """
    alphabet = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(32))
    full_key = f"sk_live_{random_part}"
    prefix   = full_key[:16]          # "sk_live_" + first 8 chars
    key_hash = pwd_context.hash(full_key)
    return full_key, prefix, key_hash


def verify_api_key(plain_key: str, key_hash: str) -> bool:
    return pwd_context.verify(plain_key, key_hash)


# ── Workspace slug ─────────────────────────────────────────
def slugify(name: str) -> str:
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = re.sub(r"^-+|-+$", "", slug)
    return slug[:50]
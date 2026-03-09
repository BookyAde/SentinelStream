"""
SentinelStream Auth Dependencies
FastAPI Depends() helpers for extracting the current user and workspace from requests.
"""

import uuid
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.core.auth import decode_access_token, verify_api_key
from app.db.postgres import get_db
from app.models.workspace import User, Workspace, WorkspaceMember, APIKey

# ── Schemes ────────────────────────────────────────────────
bearer_scheme   = HTTPBearer(auto_error=False)
api_key_scheme  = APIKeyHeader(name="X-API-Key", auto_error=False)


# ── JWT user extraction ────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    return user


# ── Workspace membership ───────────────────────────────────
async def get_current_workspace(
    workspace_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Workspace:
    """Verify user is a member of the requested workspace."""
    result = await db.execute(
        select(Workspace).where(Workspace.slug == workspace_slug)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    membership = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not membership.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    return workspace


# ── API Key authentication ─────────────────────────────────
async def get_workspace_from_api_key(
    api_key: str | None = Security(api_key_scheme),
    db: AsyncSession = Depends(get_db),
) -> Workspace:
    """
    Validates X-API-Key header, returns the associated workspace.
    Used by event ingestion endpoints so external apps can send events.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Pass it as X-API-Key header.",
        )

    if not api_key.startswith("sk_live_"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key format")

    # Look up by prefix (first 16 chars) then verify full hash
    prefix = api_key[:16]
    result = await db.execute(
        select(APIKey).where(APIKey.key_prefix == prefix, APIKey.is_active == True)
    )
    key_record = result.scalar_one_or_none()

    if not key_record or not verify_api_key(api_key, key_record.key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    # Update last_used timestamp
    key_record.last_used = datetime.now(timezone.utc)
    await db.commit()

    # Load workspace
    result = await db.execute(
        select(Workspace).where(Workspace.id == key_record.workspace_id)
    )
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Workspace not found")

    return workspace
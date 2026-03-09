"""
SentinelStream Auth Routes
/auth/register, /auth/login, /workspaces/*, /api-keys/*
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.auth import (
    hash_password, verify_password,
    create_access_token, generate_api_key, slugify
)
from app.core.dependencies import get_current_user, get_current_workspace
from app.db.postgres import get_db
from app.models.workspace import User, Workspace, WorkspaceMember, APIKey, MemberRole
from app.schemas.auth import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
    UserResponse, WorkspaceResponse, CreateWorkspaceRequest,
    APIKeyCreate, APIKeyResponse, APIKeyCreatedResponse,
    InviteMemberRequest, MemberResponse,
)

router = APIRouter()


# ══════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════

@router.post("/auth/register", response_model=RegisterResponse, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user, create their first workspace, and generate an API key."""

    # Check email not already taken
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create user
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    await db.flush()  # get user.id without committing

    # Create workspace
    base_slug = slugify(payload.workspace_name)
    slug = base_slug
    counter = 1
    while True:
        exists = await db.execute(select(Workspace).where(Workspace.slug == slug))
        if not exists.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    workspace = Workspace(name=payload.workspace_name, slug=slug)
    db.add(workspace)
    await db.flush()

    # Add user as owner
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role=MemberRole.OWNER,
    )
    db.add(member)

    # Generate first API key
    full_key, prefix, key_hash = generate_api_key()
    api_key = APIKey(
        workspace_id=workspace.id,
        created_by=user.id,
        name="Default",
        key_prefix=prefix,
        key_hash=key_hash,
        is_active=True,
    )
    db.add(api_key)
    await db.commit()

    token = create_access_token(str(user.id))

    return RegisterResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        workspace_slug=workspace.slug,
        access_token=token,
        api_key=full_key,   # shown ONCE
    )


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Account is disabled")

    token = create_access_token(str(user.id))
    return LoginResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
    )


@router.get("/auth/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user


# ══════════════════════════════════════════════════════════
# WORKSPACES
# ══════════════════════════════════════════════════════════

@router.get("/workspaces", response_model=list[WorkspaceResponse])
async def list_workspaces(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
    )
    return result.scalars().all()


@router.post("/workspaces", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    payload: CreateWorkspaceRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base_slug = slugify(payload.name)
    slug = base_slug
    counter = 1
    while True:
        exists = await db.execute(select(Workspace).where(Workspace.slug == slug))
        if not exists.scalar_one_or_none():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1

    workspace = Workspace(name=payload.name, slug=slug)
    db.add(workspace)
    await db.flush()

    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=MemberRole.OWNER)
    db.add(member)
    await db.commit()
    return workspace


@router.get("/workspaces/{workspace_slug}", response_model=WorkspaceResponse)
async def get_workspace(workspace: Workspace = Depends(get_current_workspace)):
    return workspace


# ── Members ────────────────────────────────────────────────

@router.get("/workspaces/{workspace_slug}/members", response_model=list[MemberResponse])
async def list_members(
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace.id)
    )
    rows = result.all()
    return [
        MemberResponse(
            user_id=member.user_id,
            email=user.email,
            full_name=user.full_name,
            role=member.role.value,
            joined_at=member.joined_at,
        )
        for member, user in rows
    ]


@router.post("/workspaces/{workspace_slug}/members", status_code=201)
async def invite_member(
    payload: InviteMemberRequest,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Invite an existing user to the workspace by email."""
    result = await db.execute(select(User).where(User.email == payload.email))
    invitee = result.scalar_one_or_none()
    if not invitee:
        raise HTTPException(status_code=404, detail="No user with that email found")

    existing = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == invitee.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User is already a member")

    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=invitee.id,
        role=MemberRole(payload.role),
    )
    db.add(member)
    await db.commit()
    return {"detail": f"{payload.email} added to workspace"}


@router.delete("/workspaces/{workspace_slug}/members/{user_id}", status_code=204)
async def remove_member(
    user_id: uuid.UUID,
    workspace: Workspace = Depends(get_current_workspace),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    await db.delete(member)
    await db.commit()


# ══════════════════════════════════════════════════════════
# API KEYS
# ══════════════════════════════════════════════════════════

@router.get("/workspaces/{workspace_slug}/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(APIKey).where(APIKey.workspace_id == workspace.id)
    )
    return result.scalars().all()


@router.post("/workspaces/{workspace_slug}/api-keys", response_model=APIKeyCreatedResponse, status_code=201)
async def create_api_key(
    payload: APIKeyCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new API key. The full key is returned ONCE — store it safely."""
    full_key, prefix, key_hash = generate_api_key()
    api_key = APIKey(
        workspace_id=workspace.id,
        created_by=user.id,
        name=payload.name,
        key_prefix=prefix,
        key_hash=key_hash,
        is_active=True,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return APIKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        is_active=api_key.is_active,
        last_used=api_key.last_used,
        created_at=api_key.created_at,
        full_key=full_key,
    )


@router.delete("/workspaces/{workspace_slug}/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.workspace_id == workspace.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    key.is_active = False
    await db.commit()
    return {"detail": "API key revoked"}
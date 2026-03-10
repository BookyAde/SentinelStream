"""
SentinelStream Auth Routes — v2
Includes: register, verify, login, workspaces, API keys, admin panel
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import (
    hash_password, verify_password,
    create_access_token, generate_api_key, slugify
)
from app.core.dependencies import get_current_user, get_current_workspace
from app.db.postgres import get_db
from app.db.redis_client import get_redis
from app.models.workspace import User, Workspace, WorkspaceMember, APIKey, MemberRole
from app.models.event import Event
from app.schemas.auth import (
    RegisterRequest, RegisterResponse,
    LoginRequest, LoginResponse,
    UserResponse, WorkspaceResponse, CreateWorkspaceRequest,
    APIKeyCreate, APIKeyResponse, APIKeyCreatedResponse,
    InviteMemberRequest, MemberResponse,
)
from app.services.email import (
    generate_verification_code,
    send_verification_email,
    send_welcome_email,
)

router = APIRouter()
VERIFY_TTL = 60 * 15  # 15 min


async def get_superuser(user: User = Depends(get_current_user)) -> User:
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ══════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════

@router.post("/auth/register", status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    import json
    redis = get_redis()
    code  = generate_verification_code()
    await redis.setex(f"pending_reg:{payload.email}", VERIFY_TTL, json.dumps({
        "email": payload.email, "full_name": payload.full_name,
        "hashed_password": hash_password(payload.password),
        "workspace_name": payload.workspace_name, "code": code,
    }))
    await send_verification_email(payload.email, payload.full_name, code)
    return {"detail": "Verification code sent to your email", "email": payload.email, "expires": "15 minutes"}


@router.post("/auth/verify", response_model=RegisterResponse, status_code=201)
async def verify_registration(email: str, code: str, db: AsyncSession = Depends(get_db)):
    import json
    redis = get_redis()
    raw   = await redis.get(f"pending_reg:{email}")
    if not raw:
        raise HTTPException(status_code=400, detail="Code expired — please register again")
    data = json.loads(raw)
    if data["code"] != code:
        raise HTTPException(status_code=400, detail="Incorrect verification code")
    await redis.delete(f"pending_reg:{email}")

    user = User(email=data["email"], hashed_password=data["hashed_password"], full_name=data["full_name"],
                is_active=True, is_verified=True, is_superuser=False, is_suspended=False)
    db.add(user)
    await db.flush()

    base_slug = slugify(data["workspace_name"])
    slug, counter = base_slug, 1
    while True:
        exists = await db.execute(select(Workspace).where(Workspace.slug == slug))
        if not exists.scalar_one_or_none(): break
        slug = f"{base_slug}-{counter}"; counter += 1

    workspace = Workspace(name=data["workspace_name"], slug=slug)
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=MemberRole.OWNER))

    full_key, prefix, key_hash = generate_api_key()
    db.add(APIKey(workspace_id=workspace.id, created_by=user.id, name="Default",
                  key_prefix=prefix, key_hash=key_hash, is_active=True))
    await db.commit()
    await send_welcome_email(user.email, user.full_name, workspace.slug)

    return RegisterResponse(user_id=user.id, email=user.email, full_name=user.full_name,
                            workspace_slug=workspace.slug, access_token=create_access_token(str(user.id)), api_key=full_key)


@router.post("/auth/resend-code")
async def resend_code(email: str):
    import json
    redis = get_redis()
    raw   = await redis.get(f"pending_reg:{email}")
    if not raw:
        raise HTTPException(status_code=400, detail="No pending registration — please register again")
    data = json.loads(raw)
    data["code"] = generate_verification_code()
    await redis.setex(f"pending_reg:{email}", VERIFY_TTL, json.dumps(data))
    await send_verification_email(email, data["full_name"], data["code"])
    return {"detail": "New code sent"}


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user   = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if user.is_suspended:
        raise HTTPException(status_code=403, detail="Account suspended — contact support")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified — check your inbox")
    return LoginResponse(access_token=create_access_token(str(user.id)), user_id=user.id, email=user.email, full_name=user.full_name)


@router.get("/auth/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user


# ══════════════════════════════════════════════════════════
# WORKSPACES
# ══════════════════════════════════════════════════════════

@router.get("/workspaces", response_model=list[WorkspaceResponse])
async def list_workspaces(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workspace).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id).where(WorkspaceMember.user_id == user.id))
    return result.scalars().all()


@router.post("/workspaces", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(payload: CreateWorkspaceRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    base_slug = slugify(payload.name)
    slug, counter = base_slug, 1
    while True:
        exists = await db.execute(select(Workspace).where(Workspace.slug == slug))
        if not exists.scalar_one_or_none(): break
        slug = f"{base_slug}-{counter}"; counter += 1
    workspace = Workspace(name=payload.name, slug=slug)
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=MemberRole.OWNER))
    await db.commit()
    return workspace


@router.get("/workspaces/{workspace_slug}", response_model=WorkspaceResponse)
async def get_workspace(workspace: Workspace = Depends(get_current_workspace)):
    return workspace


@router.get("/workspaces/{workspace_slug}/members", response_model=list[MemberResponse])
async def list_members(workspace: Workspace = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace.id))
    return [MemberResponse(user_id=m.user_id, email=u.email, full_name=u.full_name, role=m.role.value, joined_at=m.joined_at) for m, u in result.all()]


@router.post("/workspaces/{workspace_slug}/members", status_code=201)
async def invite_member(payload: InviteMemberRequest, workspace: Workspace = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    invitee = result.scalar_one_or_none()
    if not invitee: raise HTTPException(status_code=404, detail="User not found")
    existing = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == invitee.id))
    if existing.scalar_one_or_none(): raise HTTPException(status_code=400, detail="Already a member")
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=invitee.id, role=MemberRole(payload.role)))
    await db.commit()
    return {"detail": f"{payload.email} added"}


@router.delete("/workspaces/{workspace_slug}/members/{user_id}", status_code=204)
async def remove_member(user_id: uuid.UUID, workspace: Workspace = Depends(get_current_workspace), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user_id == current_user.id: raise HTTPException(status_code=400, detail="Cannot remove yourself")
    result = await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user_id))
    member = result.scalar_one_or_none()
    if not member: raise HTTPException(status_code=404, detail="Member not found")
    await db.delete(member); await db.commit()


# ══════════════════════════════════════════════════════════
# API KEYS
# ══════════════════════════════════════════════════════════

@router.get("/workspaces/{workspace_slug}/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(workspace: Workspace = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(APIKey).where(APIKey.workspace_id == workspace.id))
    return result.scalars().all()


@router.post("/workspaces/{workspace_slug}/api-keys", response_model=APIKeyCreatedResponse, status_code=201)
async def create_api_key(payload: APIKeyCreate, workspace: Workspace = Depends(get_current_workspace), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    full_key, prefix, key_hash = generate_api_key()
    api_key = APIKey(workspace_id=workspace.id, created_by=user.id, name=payload.name, key_prefix=prefix, key_hash=key_hash, is_active=True)
    db.add(api_key); await db.commit(); await db.refresh(api_key)
    return APIKeyCreatedResponse(id=api_key.id, name=api_key.name, key_prefix=api_key.key_prefix, is_active=api_key.is_active, last_used=api_key.last_used, created_at=api_key.created_at, full_key=full_key)


@router.delete("/workspaces/{workspace_slug}/api-keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: uuid.UUID, workspace: Workspace = Depends(get_current_workspace), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(APIKey).where(APIKey.id == key_id, APIKey.workspace_id == workspace.id))
    key = result.scalar_one_or_none()
    if not key: raise HTTPException(status_code=404, detail="Key not found")
    key.is_active = False; await db.commit()


# ══════════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════════

@router.get("/admin/stats")
async def admin_stats(admin: User = Depends(get_superuser), db: AsyncSession = Depends(get_db)):
    return {
        "total_users":      (await db.execute(select(func.count()).select_from(User))).scalar(),
        "total_workspaces": (await db.execute(select(func.count()).select_from(Workspace))).scalar(),
        "total_events":     (await db.execute(select(func.count()).select_from(Event))).scalar(),
        "suspended_users":  (await db.execute(select(func.count()).select_from(User).where(User.is_suspended == True))).scalar(),
        "unverified_users": (await db.execute(select(func.count()).select_from(User).where(User.is_verified == False))).scalar(),
    }


@router.get("/admin/users")
async def admin_list_users(page: int = 1, page_size: int = 50, admin: User = Depends(get_superuser), db: AsyncSession = Depends(get_db)):
    offset = (page - 1) * page_size
    result = await db.execute(select(User).order_by(User.created_at.desc()).offset(offset).limit(page_size))
    users  = result.scalars().all()
    total  = (await db.execute(select(func.count()).select_from(User))).scalar()
    out = []
    for u in users:
        ws = await db.execute(select(Workspace).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id).where(WorkspaceMember.user_id == u.id))
        out.append({"id": str(u.id), "email": u.email, "full_name": u.full_name, "is_verified": u.is_verified,
                    "is_suspended": u.is_suspended, "is_superuser": u.is_superuser,
                    "workspaces": [w.slug for w in ws.scalars().all()], "created_at": u.created_at.isoformat()})
    return {"total": total, "page": page, "items": out}


@router.get("/admin/workspaces")
async def admin_list_workspaces(page: int = 1, page_size: int = 50, admin: User = Depends(get_superuser), db: AsyncSession = Depends(get_db)):
    offset = (page - 1) * page_size
    result = await db.execute(select(Workspace).order_by(Workspace.created_at.desc()).offset(offset).limit(page_size))
    total  = (await db.execute(select(func.count()).select_from(Workspace))).scalar()
    out = []
    for w in result.scalars().all():
        mc = (await db.execute(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == w.id))).scalar()
        out.append({"id": str(w.id), "name": w.name, "slug": w.slug, "member_count": mc, "created_at": w.created_at.isoformat()})
    return {"total": total, "page": page, "items": out}


@router.post("/admin/users/{user_id}/suspend")
async def suspend_user(user_id: uuid.UUID, admin: User = Depends(get_superuser), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user: raise HTTPException(status_code=404, detail="User not found")
    if user.is_superuser: raise HTTPException(status_code=400, detail="Cannot suspend admin")
    user.is_suspended = True; await db.commit()
    return {"detail": f"{user.email} suspended"}


@router.post("/admin/users/{user_id}/unsuspend")
async def unsuspend_user(user_id: uuid.UUID, admin: User = Depends(get_superuser), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user   = result.scalar_one_or_none()
    if not user: raise HTTPException(status_code=404, detail="User not found")
    user.is_suspended = False; await db.commit()
    return {"detail": f"{user.email} unsuspended"}


@router.post("/admin/make-superuser")
async def make_superuser(target_email: str, admin: User = Depends(get_superuser), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == target_email))
    user   = result.scalar_one_or_none()
    if not user: raise HTTPException(status_code=404, detail="User not found")
    user.is_superuser = True; await db.commit()
    return {"detail": f"{target_email} is now superuser"}
"""
SentinelStream Auth Schemas
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator


# ── Register ───────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email:          EmailStr
    password:       str
    full_name:      str
    workspace_name: str   # e.g. "Acme Corp" — auto-creates first workspace

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class RegisterResponse(BaseModel):
    user_id:        uuid.UUID
    email:          str
    full_name:      str
    workspace_slug: str
    access_token:   str
    api_key:        str    # shown ONCE — user must copy it now
    token_type:     str = "bearer"


# ── Login ──────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user_id:      uuid.UUID
    email:        str
    full_name:    str


# ── User ───────────────────────────────────────────────────
class UserResponse(BaseModel):
    id:          uuid.UUID
    email:       str
    full_name:   str
    is_active:   bool
    is_verified: bool
    created_at:  datetime

    class Config:
        from_attributes = True


# ── Workspace ──────────────────────────────────────────────
class WorkspaceResponse(BaseModel):
    id:         uuid.UUID
    name:       str
    slug:       str
    created_at: datetime

    class Config:
        from_attributes = True


class CreateWorkspaceRequest(BaseModel):
    name: str


# ── API Keys ───────────────────────────────────────────────
class APIKeyCreate(BaseModel):
    name: str   # e.g. "Production", "Staging"


class APIKeyResponse(BaseModel):
    id:         uuid.UUID
    name:       str
    key_prefix: str
    is_active:  bool
    last_used:  datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreatedResponse(APIKeyResponse):
    full_key: str   # Only returned once at creation


# ── Invite ─────────────────────────────────────────────────
class InviteMemberRequest(BaseModel):
    email: EmailStr
    role:  str = "member"


class MemberResponse(BaseModel):
    user_id:   uuid.UUID
    email:     str
    full_name: str
    role:      str
    joined_at: datetime
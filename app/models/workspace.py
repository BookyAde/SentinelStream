"""
SentinelStream Workspace Model
A workspace is an isolated container for a team's events, API keys, and members.
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import String, DateTime, Boolean, ForeignKey, Enum, Index, func, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


class MemberRole(str, PyEnum):
    OWNER  = "owner"
    ADMIN  = "admin"
    MEMBER = "member"


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str]     = mapped_column(String(100), nullable=False)
    slug: Mapped[str]     = mapped_column(String(100), unique=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    members:  Mapped[list["WorkspaceMember"]] = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    api_keys: Mapped[list["APIKey"]]          = relationship("APIKey",          back_populates="workspace", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Workspace slug={self.slug}>"


class User(Base):
    __tablename__ = "users"

    id:              Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email:           Mapped[str]       = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str]       = mapped_column(String(255), nullable=False)
    full_name:       Mapped[str]       = mapped_column(String(100), nullable=False)
    is_active:       Mapped[bool]      = mapped_column(Boolean, default=True, nullable=False)
    is_verified:     Mapped[bool]      = mapped_column(Boolean, default=False, nullable=False)
    is_superuser:    Mapped[bool]      = mapped_column(Boolean, default=False, nullable=False)
    is_suspended:    Mapped[bool]      = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    memberships: Mapped[list["WorkspaceMember"]] = relationship("WorkspaceMember", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User email={self.email}>"


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id:           Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id:      Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), ForeignKey("users.id",       ondelete="CASCADE"), nullable=False)
    role:         Mapped[MemberRole]  = mapped_column(Enum(MemberRole), default=MemberRole.MEMBER, nullable=False)
    joined_at:    Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="members")
    user:      Mapped["User"]      = relationship("User",      back_populates="memberships")

    __table_args__ = (
        Index("ix_workspace_members_workspace_id", "workspace_id"),
        Index("ix_workspace_members_user_id",      "user_id"),
    )


class APIKey(Base):
    __tablename__ = "api_keys"

    id:           Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    created_by:   Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id",       ondelete="SET NULL"), nullable=True)

    name:       Mapped[str]       = mapped_column(String(100), nullable=False)               # Human label e.g. "Production"
    key_prefix: Mapped[str]       = mapped_column(String(12),  nullable=False)               # e.g. "sk_live_xxxx" — shown in UI
    key_hash:   Mapped[str]       = mapped_column(String(255), nullable=False, unique=True)  # bcrypt hash of full key
    is_active:  Mapped[bool]      = mapped_column(Boolean, default=True, nullable=False)
    last_used:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="api_keys")

    __table_args__ = (
        Index("ix_api_keys_workspace_id", "workspace_id"),
        Index("ix_api_keys_key_prefix",   "key_prefix"),
    )

    def __repr__(self) -> str:
        return f"<APIKey prefix={self.key_prefix} workspace={self.workspace_id}>"
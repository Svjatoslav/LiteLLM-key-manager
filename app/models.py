from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


json_list_type = JSON().with_variant(JSONB, "postgresql")
json_dict_type = JSON().with_variant(JSONB, "postgresql")


class TeamRole(StrEnum):
    lead = "lead"


class KeyStatus(StrEnum):
    active = "active"
    blocked = "blocked"
    deleted = "deleted"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    memberships: Mapped[list[TeamMember]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    litellm_team_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    models: Mapped[list[str]] = mapped_column(MutableList.as_mutable(json_list_type), default=list, nullable=False)
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    members: Mapped[list[TeamMember]] = relationship(back_populates="team", cascade="all, delete-orphan")
    keys: Mapped[list[EmployeeKey]] = relationship(back_populates="team")
    lead_api_keys: Mapped[list[LeadApiKey]] = relationship(back_populates="team")


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[TeamRole] = mapped_column(SAEnum(TeamRole), default=TeamRole.lead, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    team: Mapped[Team] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    team: Mapped[Team] = relationship()
    created_by: Mapped[User] = relationship()


class LeadApiKey(Base):
    __tablename__ = "lead_api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    lead_email: Mapped[str] = mapped_column(String(320), index=True)
    litellm_user_id: Mapped[str] = mapped_column(String(255), index=True)
    key_alias: Mapped[str] = mapped_column(String(255), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    encrypted_key: Mapped[str] = mapped_column(Text)
    masked_key: Mapped[str] = mapped_column(String(80))
    litellm_token_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    models_snapshot: Mapped[list[str]] = mapped_column(MutableList.as_mutable(json_list_type), default=list, nullable=False)
    status: Mapped[KeyStatus] = mapped_column(SAEnum(KeyStatus), default=KeyStatus.active, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    team: Mapped[Team] = relationship(back_populates="lead_api_keys")
    created_by: Mapped[User] = relationship()


class EmployeeKey(Base):
    __tablename__ = "employee_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    owner_name: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(String(500), default="")
    key_type: Mapped[str] = mapped_column(String(40), default="Coding")
    duration: Mapped[str | None] = mapped_column(String(40), nullable=True)
    key_alias: Mapped[str] = mapped_column(String(255), index=True)
    litellm_token_id: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    encrypted_key: Mapped[str] = mapped_column(Text)
    masked_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[KeyStatus] = mapped_column(SAEnum(KeyStatus), default=KeyStatus.active, nullable=False)
    models_snapshot: Mapped[list[str]] = mapped_column(MutableList.as_mutable(json_list_type), default=list, nullable=False)
    limits_snapshot: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_dict_type), default=dict, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rotated_from_key_id: Mapped[str | None] = mapped_column(ForeignKey("employee_keys.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    team: Mapped[Team] = relationship(back_populates="keys")
    created_by: Mapped[User] = relationship()


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_dict_type), default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AdGroupMapping(Base):
    __tablename__ = "ad_group_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ad_group_dn: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True)
    role: Mapped[TeamRole | None] = mapped_column(SAEnum(TeamRole), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

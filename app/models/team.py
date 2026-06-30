"""
Modelos para Teams, Members, Visibility Rules y Emergency Events.

Esquema: team (PostgreSQL)
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    pass


class Team(SQLModel, table=True):
    """Representa un grupo lógico de usuarios (familia, flotilla, evento, etc.)."""

    __tablename__ = "teams"
    __table_args__ = (
        Index("idx_team_account", "account_id"),
        Index("idx_team_type", "type"),
        Index("idx_team_expires_at", "expires_at"),
        {"schema": "team"},
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    account_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    name: str = Field(sa_column=Column(Text, nullable=False))
    type: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(
        default="ACTIVE",
        sa_column=Column(Text, nullable=False, server_default=text("'ACTIVE'")),
    )
    timezone: str = Field(
        default="UTC",
        sa_column=Column(Text, nullable=False, server_default=text("'UTC'")),
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
    )
    auto_delete_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
    )
    team_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )
    created_by_user_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )

    members: list["TeamMember"] = Relationship(back_populates="team")
    visibility_rules: list["TeamVisibilityRule"] = Relationship(back_populates="team")
    invites: list["TeamInvite"] = Relationship(back_populates="team")


class TeamMember(SQLModel, table=True):
    """Representa la pertenencia de un usuario a un team."""

    __tablename__ = "members"
    __table_args__ = (
        Index("idx_team_members_team", "team_id"),
        Index("idx_team_members_user", "user_id"),
        {"schema": "team"},
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    team_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("team.teams.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    user_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    role: str = Field(sa_column=Column(Text, nullable=False))
    invited_by_user_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    joined_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )
    member_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )

    team: Optional[Team] = Relationship(back_populates="members")


class TeamVisibilityRule(SQLModel, table=True):
    """Define cómo un rol sujeto comparte ubicación con un rol visor."""

    __tablename__ = "visibility_rules"
    __table_args__ = (
        Index("idx_visibility_team", "team_id"),
        Index("idx_visibility_rules_team_active", "team_id", "is_active"),
        {"schema": "team"},
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    team_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("team.teams.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    subject_role: str = Field(sa_column=Column(Text, nullable=False))
    viewer_role: str = Field(sa_column=Column(Text, nullable=False))
    access_mode: str = Field(sa_column=Column(Text, nullable=False))
    schedule: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    rule_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )

    team: Optional[Team] = Relationship(back_populates="visibility_rules")


class TeamInvite(SQLModel, table=True):
    """Invitación a un team por QR, link, email o teléfono."""

    __tablename__ = "invites"
    __table_args__ = (
        Index("idx_team_invites_team", "team_id"),
        Index("idx_team_invites_token_hash", "token_hash"),
        Index("idx_team_invites_active", "team_id", "is_active"),
        {"schema": "team"},
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    team_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("team.teams.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    created_by_user_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    invite_method: str = Field(sa_column=Column(Text, nullable=False))
    invited_role: str = Field(sa_column=Column(Text, nullable=False))
    token_hash: str = Field(sa_column=Column(Text, nullable=False))
    expires_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), nullable=False)
    )
    max_uses: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
    )
    used_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    invite_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )

    team: Optional[Team] = Relationship(back_populates="invites")


class EmergencyEvent(SQLModel, table=True):
    """Evento de emergencia activado por un usuario dentro de un team."""

    __tablename__ = "emergency_events"
    __table_args__ = (
        Index("idx_emergency_events_team_status", "team_id", "status"),
        {"schema": "team"},
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    team_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("team.teams.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    triggered_by_user_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id"),
            nullable=False,
        )
    )
    emergency_type: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(
        default="ACTIVE",
        sa_column=Column(Text, nullable=False, server_default=text("'ACTIVE'")),
    )
    started_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("now()"),
        ),
    )
    ended_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
    )
    event_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )

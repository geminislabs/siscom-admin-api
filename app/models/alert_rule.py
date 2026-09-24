from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import TIMESTAMP, Boolean, Column, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel


class AlertRule(SQLModel, table=True):
    """Regla configurable para generación externa de alertas."""

    __tablename__ = "alert_rules"

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )

    organization_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    # ON DELETE SET NULL en DDL requiere nullable=True.
    created_by: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    name: str = Field(sa_column=Column(Text, nullable=False))
    type: str = Field(sa_column=Column(Text, nullable=False))
    config: dict = Field(sa_column=Column(JSONB, nullable=False))

    fingerprint: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=False, unique=True),
    )

    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, default=True, nullable=False),
    )

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            server_default=text("now()"),
            nullable=False,
        ),
    )

    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            server_default=text("now()"),
            nullable=False,
        ),
    )


class AlertRuleUnit(SQLModel, table=True):
    """Asignación de regla a una o más unidades."""

    __tablename__ = "alert_rule_units"

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )

    rule_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("alert_rules.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    unit_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("units.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            server_default=text("now()"),
            nullable=False,
        ),
    )

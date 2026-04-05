from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import TIMESTAMP, Column, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel


class Alert(SQLModel, table=True):
    """Alerta ya generada por un sistema externo."""

    __tablename__ = "alerts"

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

    rule_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("alert_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    unit_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("units.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    source_type: str = Field(sa_column=Column(Text, nullable=False))
    source_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    type: str = Field(sa_column=Column(Text, nullable=False))
    payload: Optional[dict] = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )

    occurred_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), nullable=False)
    )

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            server_default=text("now()"),
            nullable=False,
        ),
    )

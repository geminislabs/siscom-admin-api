from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Boolean, Column, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel


class MobilityDevice(SQLModel, table=True):
    __tablename__ = "devices"
    __table_args__ = (
        Index(
            "uq_mobility_devices_notification_device",
            "notification_device_id",
            unique=True,
            postgresql_where=text("notification_device_id IS NOT NULL"),
        ),
        {"schema": "mobility"},
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    user_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    device_type: str = Field(sa_column=Column(Text, nullable=False))
    platform: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    device_name: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    external_device_id: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    app_version: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    os_version: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    last_seen_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    mobility_metadata: dict[str, Any] = Field(
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
    notification_device_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("user_devices.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, Column, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, SQLModel


class UserDevice(SQLModel, table=True):
    __tablename__ = "user_devices"
    __table_args__ = (
        Index("idx_user_devices_user_id", "user_id"),
        Index("idx_user_devices_device_token", "device_token"),
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
    device_token: str = Field(sa_column=Column(Text, nullable=False))
    platform: str = Field(sa_column=Column(Text, nullable=False))
    endpoint_arn: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, server_default=text("true"), nullable=False),
    )
    last_seen_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            server_default=text("now()"),
            nullable=True,
        ),
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            server_default=text("now()"),
            nullable=True,
        ),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            server_default=text("now()"),
            nullable=True,
        ),
    )

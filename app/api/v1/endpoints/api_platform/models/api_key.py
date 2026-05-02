from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Column, Field, SQLModel


class ApiKey(SQLModel, table=True):
    __tablename__ = "api_keys"
    __table_args__ = {"schema": "api_platform"}

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    organization_id: UUID
    product_id: UUID
    name: str
    key_hash: str
    prefix: str
    status: str = Field(default="ACTIVE")
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.TIMESTAMP(timezone=True), server_default=text("now()")),
    )
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    key_metadata: Optional[dict] = Field(
        default=None, sa_column=Column("metadata", JSONB)
    )

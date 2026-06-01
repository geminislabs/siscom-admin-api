from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Column, Field, SQLModel


class ApiThrottleEvent(SQLModel, table=True):
    __tablename__ = "api_throttle_events"
    __table_args__ = {"schema": "api_platform"}

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    api_key_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    type: str
    limit_value: Optional[int] = None
    actual_value: Optional[int] = None
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.TIMESTAMP(timezone=True), server_default=text("now()")),
    )

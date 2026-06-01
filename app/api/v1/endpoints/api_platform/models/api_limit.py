from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Column, Field, SQLModel


class ApiLimit(SQLModel, table=True):
    __tablename__ = "api_limits"
    __table_args__ = {"schema": "api_platform"}

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    plan_id: UUID
    rpm_limit: Optional[int] = None
    daily_limit: Optional[int] = None
    monthly_limit: Optional[int] = None
    burst_limit: Optional[int] = None
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.TIMESTAMP(timezone=True), server_default=text("now()")),
    )

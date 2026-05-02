from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Column, Field, SQLModel


class ApiAlert(SQLModel, table=True):
    __tablename__ = "api_alerts"
    __table_args__ = {"schema": "api_platform"}

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    organization_id: Optional[UUID] = None
    api_key_id: Optional[UUID] = None
    type: str
    threshold: Optional[float] = None
    time_window: Optional[str] = None
    enabled: bool = Field(default=True)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.TIMESTAMP(timezone=True), server_default=text("now()")),
    )

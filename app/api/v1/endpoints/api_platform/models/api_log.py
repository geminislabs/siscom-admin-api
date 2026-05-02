from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Column, Field, SQLModel


class ApiRequestLog(SQLModel, table=True):
    __tablename__ = "api_request_logs"
    __table_args__ = {"schema": "api_platform"}

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    api_key_id: UUID
    organization_id: UUID
    method: str
    endpoint: str
    status_code: int
    latency_ms: int
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    request_size: Optional[int] = None
    response_size: Optional[int] = None
    error_code: Optional[str] = None
    created_at: datetime = Field(
        sa_column=Column(
            sa.TIMESTAMP(timezone=True),
            primary_key=True,
            nullable=False,
            server_default=text("now()"),
        )
    )

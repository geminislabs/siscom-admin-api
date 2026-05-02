from datetime import date, datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Column, Field, SQLModel


class ApiUsageMinute(SQLModel, table=True):
    __tablename__ = "api_usage_minute"
    __table_args__ = {"schema": "api_platform"}

    api_key_id: UUID = Field(
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True)
    )
    organization_id: Optional[UUID] = None
    bucket: datetime = Field(
        sa_column=Column(sa.TIMESTAMP(timezone=True), primary_key=True)
    )
    request_count: int
    error_count: int
    sum_latency: int
    max_latency: Optional[int] = None
    status_2xx: Optional[int] = None
    status_4xx: Optional[int] = None
    status_5xx: Optional[int] = None


class ApiUsageDaily(SQLModel, table=True):
    __tablename__ = "api_usage_daily"
    __table_args__ = {"schema": "api_platform"}

    api_key_id: UUID = Field(
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True)
    )
    organization_id: Optional[UUID] = None
    day: date = Field(sa_column=Column(sa.Date, primary_key=True))
    request_count: int
    error_count: int


class ApiUsageMonthly(SQLModel, table=True):
    __tablename__ = "api_usage_monthly"
    __table_args__ = {"schema": "api_platform"}

    api_key_id: UUID = Field(
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True)
    )
    organization_id: Optional[UUID] = None
    month: date = Field(sa_column=Column(sa.Date, primary_key=True))
    request_count: int
    error_count: int


class ApiUsageCounter(SQLModel, table=True):
    __tablename__ = "api_usage_counters"
    __table_args__ = {"schema": "api_platform"}

    api_key_id: UUID = Field(
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True)
    )
    current_minute_count: Optional[int] = None
    current_day_count: Optional[int] = None
    current_month_count: Optional[int] = None
    updated_at: datetime = Field(
        sa_column=Column(sa.TIMESTAMP(timezone=True), nullable=False)
    )

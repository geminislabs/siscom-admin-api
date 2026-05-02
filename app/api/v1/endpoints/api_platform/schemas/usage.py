from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class UsageSummary(BaseModel):
    active_keys: int
    requests_today: int
    requests_month: int
    error_rate: float  # 0.0 - 1.0


class UsageByKeyItem(BaseModel):
    api_key_id: UUID
    name: str
    requests: int
    percentage: float


class TimeseriesPoint(BaseModel):
    bucket: datetime
    request_count: int
    error_count: int


class LimitsStatus(BaseModel):
    rpm_limit: Optional[int]
    rpm_current: Optional[int]
    daily_limit: Optional[int]
    daily_current: Optional[int]
    monthly_limit: Optional[int]
    monthly_current: Optional[int]
    burst_limit: Optional[int]
    burst_current: Optional[int]

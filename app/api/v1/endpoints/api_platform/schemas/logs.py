from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class LogEntry(BaseModel):
    id: UUID
    api_key_id: UUID
    organization_id: UUID
    method: str
    endpoint: str
    status_code: int
    latency_ms: int
    ip: Optional[str]
    user_agent: Optional[str]
    request_size: Optional[int]
    response_size: Optional[int]
    error_code: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class LogsPage(BaseModel):
    items: list[LogEntry]
    next_cursor: Optional[str]
    limit: int


class LogsStats(BaseModel):
    requests_today: int
    success_rate: float  # 0.0 - 1.0
    p50_latency_ms: Optional[float]
    errors_24h: int

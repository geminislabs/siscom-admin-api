from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AlertCreate(BaseModel):
    type: str = Field(pattern="^(ERROR_RATE|USAGE_THRESHOLD)$")
    threshold: Optional[float] = None
    time_window: Optional[str] = Field(None, max_length=10)
    api_key_id: Optional[UUID] = None


class AlertUpdate(BaseModel):
    enabled: bool


class AlertOut(BaseModel):
    id: UUID
    organization_id: Optional[UUID]
    api_key_id: Optional[UUID]
    type: str
    threshold: Optional[float]
    time_window: Optional[str]
    enabled: bool
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}

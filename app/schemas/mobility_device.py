from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MobilityDeviceCreateIn(BaseModel):
    device_type: Literal["PHONE", "WATCH", "BLE_TAG", "WEARABLE"]
    platform: Optional[str] = None
    device_name: Optional[str] = None
    external_device_id: Optional[str] = None
    app_version: Optional[str] = None
    os_version: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    notification_device_id: Optional[UUID] = None


class MobilityDeviceOut(BaseModel):
    id: UUID
    user_id: UUID
    device_type: str
    platform: Optional[str] = None
    device_name: Optional[str] = None
    external_device_id: Optional[str] = None
    app_version: Optional[str] = None
    os_version: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    is_active: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    notification_device_id: Optional[UUID] = None

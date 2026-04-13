from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DeviceRegisterIn(BaseModel):
    device_token: str = Field(..., min_length=1)
    platform: Literal["ios", "android"]


class DeviceRegisterOut(BaseModel):
    device_token: str
    platform: str
    endpoint_arn: Optional[str] = None
    is_active: bool
    last_seen_at: Optional[datetime] = None


class DeviceDeactivateIn(BaseModel):
    device_token: str = Field(..., min_length=1)


class DeviceDeactivateOut(BaseModel):
    message: str
    device_token: str
    is_active: bool

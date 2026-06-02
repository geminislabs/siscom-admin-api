from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MobilityLocationPayload(BaseModel):
    recorded_at: datetime
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    accuracy_m: Optional[float] = None
    speed_mps: Optional[float] = None
    heading: Optional[float] = None
    altitude_m: Optional[float] = None
    battery_level: Optional[float] = Field(default=None, ge=0, le=100)
    motion_state: Optional[str] = None
    h3_index: Optional[str] = None
    h3_resolution: Optional[int] = Field(default=None, ge=0, le=15)


class MobilityLocationIn(MobilityLocationPayload):
    device_id: UUID


class MobilityLocationBatchIn(BaseModel):
    device_id: UUID
    locations: list[MobilityLocationPayload] = Field(..., min_length=1)


class MobilityLocationBatchItemOut(BaseModel):
    recorded_at: str
    received_at: str
    lat: float
    lon: float
    accuracy_m: Optional[float] = None
    speed_mps: Optional[float] = None
    heading: Optional[float] = None
    altitude_m: Optional[float] = None
    battery_level: Optional[float] = None
    motion_state: Optional[str] = None
    h3_index: Optional[str] = None
    h3_resolution: Optional[int] = None


class MobilityLocationBatchOut(BaseModel):
    device_id: UUID
    locations: list[MobilityLocationBatchItemOut]


class MobilityLocationOut(BaseModel):
    device_id: UUID
    recorded_at: str
    received_at: str
    lat: float
    lon: float
    accuracy_m: Optional[float] = None
    speed_mps: Optional[float] = None
    heading: Optional[float] = None
    altitude_m: Optional[float] = None
    battery_level: Optional[float] = None
    motion_state: Optional[str] = None
    h3_index: Optional[str] = None
    h3_resolution: Optional[int] = None


def to_utc_iso_z(value: datetime) -> str:
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None).isoformat() + "Z"

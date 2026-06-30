"""Schemas para Emergency Events."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EmergencyType(str, Enum):
    """Tipos de emergencia soportados."""

    SOS = "SOS"
    PANIC = "PANIC"
    ACCIDENT = "ACCIDENT"
    MEDICAL = "MEDICAL"
    OTHER = "OTHER"


class EmergencyEventStatus(str, Enum):
    """Estados de un evento de emergencia."""

    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class EmergencyEventCreate(BaseModel):
    """Schema para crear un evento de emergencia."""

    emergency_type: EmergencyType
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmergencyEventOut(BaseModel):
    """Schema de respuesta para eventos de emergencia."""

    id: UUID
    team_id: UUID
    triggered_by_user_id: UUID
    emergency_type: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    metadata: dict[str, Any]

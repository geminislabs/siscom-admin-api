from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class UserCommandType(str, Enum):
    ENGINE_STOP = "ENGINE_STOP"
    ENGINE_RESUME = "ENGINE_RESUME"


class UserCommandConfirmation(BaseModel):
    accepted_risk: bool = Field(
        ..., description="Confirmación explícita del riesgo para comandos críticos"
    )
    password: str = Field(..., description="Contraseña del usuario")


class UserCommandCreate(BaseModel):
    command_type: UserCommandType
    unit_id: UUID
    confirmation: Optional[UserCommandConfirmation] = None

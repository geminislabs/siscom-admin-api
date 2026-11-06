from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# Tipos de roles permitidos
UserRole = Literal["viewer", "editor", "admin"]


class UserUnitCreate(BaseModel):
    """Schema para otorgar acceso de un usuario a una unidad"""

    user_id: UUID = Field(..., description="ID del usuario a quien se otorga acceso")
    unit_id: UUID = Field(..., description="ID de la unidad")
    role: UserRole = Field(
        default="viewer", description="Rol del usuario: viewer, editor, admin"
    )
    include_history: bool = Field(
        default=False,
        description=(
            "Si es true, el usuario ve también lo ocurrido en la unidad antes "
            "de la concesión. Por defecto sólo ve desde que se le concede."
        ),
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "abc12345-e89b-12d3-a456-426614174000",
                "unit_id": "def45678-e89b-12d3-a456-426614174000",
                "role": "editor",
            }
        }


class UserUnitAssign(BaseModel):
    """Schema para asignar un usuario a una unidad (endpoint jerárquico)"""

    user_id: UUID = Field(..., description="ID del usuario a quien se otorga acceso")
    role: UserRole = Field(
        default="viewer", description="Rol del usuario: viewer, editor, admin"
    )
    include_history: bool = Field(
        default=False,
        description=(
            "Si es true, el usuario ve también lo ocurrido en la unidad antes "
            "de la concesión. Por defecto sólo ve desde que se le concede."
        ),
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "abc12345-e89b-12d3-a456-426614174000",
                "role": "editor",
            }
        }


class UserUnitOut(BaseModel):
    """Schema de salida para asignación usuario→unidad"""

    id: UUID
    user_id: UUID
    unit_id: UUID
    unit_ref: Optional[UUID] = None
    granted_by: Optional[UUID] = None
    granted_at: datetime
    role: str
    include_history: bool = False

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "xyz78901-e89b-12d3-a456-426614174000",
                "user_id": "abc12345-e89b-12d3-a456-426614174000",
                "unit_id": "def45678-e89b-12d3-a456-426614174000",
                "granted_by": "master123-e89b-12d3-a456-426614174000",
                "granted_at": "2025-11-06T10:00:00Z",
                "role": "editor",
            }
        }


class UserUnitDetail(BaseModel):
    """Schema detallado de asignación con información de usuario y unidad"""

    id: UUID
    user_id: UUID
    unit_id: UUID
    unit_ref: Optional[UUID] = None
    granted_by: Optional[UUID] = None
    granted_at: datetime
    role: str
    include_history: bool = False

    # Información adicional
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None
    unit_name: Optional[str] = None
    granted_by_email: Optional[str] = None

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "xyz78901-e89b-12d3-a456-426614174000",
                "user_id": "abc12345-e89b-12d3-a456-426614174000",
                "unit_id": "def45678-e89b-12d3-a456-426614174000",
                "granted_by": "master123-e89b-12d3-a456-426614174000",
                "granted_at": "2025-11-06T10:00:00Z",
                "role": "editor",
                "user_email": "operador@cliente.com",
                "user_full_name": "Juan Operador",
                "unit_name": "Camión #45",
                "granted_by_email": "maestro@cliente.com",
            }
        }

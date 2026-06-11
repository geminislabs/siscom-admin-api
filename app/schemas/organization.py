"""
Schemas para Organizaciones y Roles.

Define los schemas de entrada/salida para:
- Organizaciones (conceptualmente = clients)
- Roles organizacionales
- Membresías
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.organization_user import OrganizationRole


class OrganizationBase(BaseModel):
    """Base para una organización."""

    name: str = Field(..., description="Nombre de la organización")


class OrganizationCreate(BaseModel):
    """Schema para crear una nueva organización."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Nombre de la organización",
    )
    billing_email: Optional[EmailStr] = Field(
        None,
        description="Email de facturación (opcional)",
    )
    country: Optional[str] = Field(
        default="MX",
        max_length=2,
        description="Código de país ISO 3166-1 alpha-2",
    )
    timezone: Optional[str] = Field(
        default="America/Mexico_City",
        description="Zona horaria IANA",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Flota Norte",
                "billing_email": "flotanorte@empresa.com",
                "country": "MX",
                "timezone": "America/Mexico_City",
            }
        }


class InternalOrganizationCreate(OrganizationCreate):
    """Crear organización desde GAC (staff) bajo una cuenta existente."""

    account_id: UUID = Field(..., description="ID del account (raíz comercial)")


class OrganizationOut(OrganizationBase):
    """Organización en respuestas."""

    id: UUID
    account_id: Optional[UUID] = None
    status: str
    billing_email: Optional[str] = None
    country: Optional[str] = None
    timezone: str = "UTC"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "account_id": "223e4567-e89b-12d3-a456-426614174000",
                "name": "Transportes García",
                "status": "ACTIVE",
                "billing_email": "facturacion@transportesgarcia.com",
                "country": "MX",
                "timezone": "America/Mexico_City",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
            }
        }


class OrganizationUpdate(BaseModel):
    """Schema para actualizar una organización."""

    name: Optional[str] = Field(None, description="Nombre de la organización")
    billing_email: Optional[EmailStr] = Field(None, description="Email de facturación")
    country: Optional[str] = Field(None, max_length=2, description="Código de país ISO")
    timezone: Optional[str] = Field(None, description="Zona horaria")

    class Config:
        json_schema_extra = {
            "example": {
                "billing_email": "nuevo-email@empresa.com",
                "timezone": "America/Mexico_City",
            }
        }


# --- Membresías y Roles ---


class OrganizationMemberOut(BaseModel):
    """Miembro de una organización en respuestas."""

    user_id: UUID
    email: str
    full_name: Optional[str] = None
    role: str
    joined_at: Optional[datetime] = None
    email_verified: bool = False

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "123e4567-e89b-12d3-a456-426614174000",
                "email": "usuario@empresa.com",
                "full_name": "Juan García",
                "role": "admin",
                "joined_at": "2024-01-15T10:30:00Z",
                "email_verified": True,
            }
        }


class OrganizationMembersListOut(BaseModel):
    """Lista de miembros de una organización."""

    members: list[OrganizationMemberOut]
    total: int

    class Config:
        json_schema_extra = {
            "example": {
                "members": [
                    {
                        "user_id": "123e4567-e89b-12d3-a456-426614174000",
                        "email": "owner@empresa.com",
                        "full_name": "Carlos López",
                        "role": "owner",
                        "joined_at": "2024-01-01T00:00:00Z",
                        "email_verified": True,
                    },
                    {
                        "user_id": "223e4567-e89b-12d3-a456-426614174000",
                        "email": "admin@empresa.com",
                        "full_name": "María Pérez",
                        "role": "admin",
                        "joined_at": "2024-01-15T10:30:00Z",
                        "email_verified": True,
                    },
                ],
                "total": 2,
            }
        }


class UpdateMemberRoleRequest(BaseModel):
    """Request para actualizar el rol de un miembro."""

    role: OrganizationRole = Field(..., description="Nuevo rol")

    class Config:
        json_schema_extra = {
            "example": {
                "role": "admin",
            }
        }


class InviteUserRequest(BaseModel):
    """Request para invitar un usuario a la organización."""

    email: EmailStr = Field(..., description="Email del usuario a invitar")
    full_name: str = Field(..., min_length=1, description="Nombre completo")
    role: OrganizationRole = Field(
        default=OrganizationRole.MEMBER, description="Rol a asignar"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "email": "nuevo@empresa.com",
                "full_name": "Pedro Martínez",
                "role": "member",
            }
        }


class AddUserToOrganizationRequest(BaseModel):
    """Request para agregar un usuario existente a la organización."""

    user_id: UUID = Field(..., description="ID del usuario a agregar")
    role: OrganizationRole = Field(
        default=OrganizationRole.MEMBER, description="Rol a asignar"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "123e4567-e89b-12d3-a456-426614174000",
                "role": "member",
            }
        }


class OrganizationUserOut(BaseModel):
    """Relación usuario-organización en respuestas."""

    id: UUID = Field(..., description="ID de la membresía")
    organization_id: UUID
    user_id: UUID
    email: str
    full_name: Optional[str] = None
    role: str
    created_at: Optional[datetime] = None
    email_verified: bool = False

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "323e4567-e89b-12d3-a456-426614174000",
                "organization_id": "123e4567-e89b-12d3-a456-426614174000",
                "user_id": "223e4567-e89b-12d3-a456-426614174000",
                "email": "usuario@empresa.com",
                "full_name": "Juan García",
                "role": "admin",
                "created_at": "2024-01-15T10:30:00Z",
                "email_verified": True,
            }
        }


class OrganizationUsersListOut(BaseModel):
    """Lista de usuarios de una organización."""

    users: list[OrganizationUserOut]
    total: int

    class Config:
        json_schema_extra = {
            "example": {
                "users": [
                    {
                        "id": "323e4567-e89b-12d3-a456-426614174000",
                        "organization_id": "123e4567-e89b-12d3-a456-426614174000",
                        "user_id": "223e4567-e89b-12d3-a456-426614174000",
                        "email": "owner@empresa.com",
                        "full_name": "Carlos López",
                        "role": "owner",
                        "created_at": "2024-01-01T00:00:00Z",
                        "email_verified": True,
                    }
                ],
                "total": 1,
            }
        }


# --- Suscripciones ---


class SubscriptionSummaryOut(BaseModel):
    """Resumen de una suscripción."""

    id: UUID
    plan_id: UUID
    plan_name: Optional[str] = None
    status: str
    started_at: datetime
    expires_at: Optional[datetime] = None
    auto_renew: bool = True
    days_remaining: Optional[int] = None

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "plan_id": "223e4567-e89b-12d3-a456-426614174000",
                "plan_name": "Plan Profesional",
                "status": "ACTIVE",
                "started_at": "2024-01-01T00:00:00Z",
                "expires_at": "2025-01-01T00:00:00Z",
                "auto_renew": True,
                "days_remaining": 180,
            }
        }


class SubscriptionsListOut(BaseModel):
    """Lista de suscripciones de una organización."""

    active: list[SubscriptionSummaryOut] = Field(default_factory=list)
    history: list[SubscriptionSummaryOut] = Field(default_factory=list)

    class Config:
        json_schema_extra = {
            "example": {
                "active": [
                    {
                        "id": "123e4567-e89b-12d3-a456-426614174000",
                        "plan_id": "223e4567-e89b-12d3-a456-426614174000",
                        "plan_name": "Plan Profesional",
                        "status": "ACTIVE",
                        "started_at": "2024-01-01T00:00:00Z",
                        "expires_at": "2025-01-01T00:00:00Z",
                        "auto_renew": True,
                        "days_remaining": 180,
                    }
                ],
                "history": [
                    {
                        "id": "323e4567-e89b-12d3-a456-426614174000",
                        "plan_id": "423e4567-e89b-12d3-a456-426614174000",
                        "plan_name": "Plan Básico",
                        "status": "EXPIRED",
                        "started_at": "2023-01-01T00:00:00Z",
                        "expires_at": "2024-01-01T00:00:00Z",
                        "auto_renew": False,
                        "days_remaining": None,
                    }
                ],
            }
        }


# --- Resumen de Organización ---


class OrganizationSummaryOut(BaseModel):
    """
    Resumen completo de una organización.

    Incluye información básica, suscripciones activas y conteo de miembros.
    """

    organization: OrganizationOut
    subscriptions: SubscriptionsListOut
    members_count: int
    capabilities: Optional[dict[str, Any]] = None

    class Config:
        json_schema_extra = {
            "example": {
                "organization": {
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "name": "Transportes García",
                    "status": "ACTIVE",
                    "billing_email": "facturacion@transportesgarcia.com",
                    "country": "MX",
                    "timezone": "America/Mexico_City",
                    "created_at": "2024-01-15T10:30:00Z",
                    "updated_at": "2024-01-15T10:30:00Z",
                },
                "subscriptions": {
                    "active": [
                        {
                            "id": "223e4567-e89b-12d3-a456-426614174000",
                            "plan_id": "323e4567-e89b-12d3-a456-426614174000",
                            "plan_name": "Plan Profesional",
                            "status": "ACTIVE",
                            "started_at": "2024-01-01T00:00:00Z",
                            "expires_at": "2025-01-01T00:00:00Z",
                            "auto_renew": True,
                            "days_remaining": 180,
                        }
                    ],
                    "history": [],
                },
                "members_count": 5,
                "capabilities": {
                    "limits": {
                        "max_devices": 50,
                        "max_users": 10,
                    },
                    "features": {
                        "ai_features": True,
                    },
                },
            }
        }

"""
Schemas para Account y Onboarding.

Account representa la raíz comercial del cliente.
SIEMPRE existe desde el primer registro.

Relación: Account 1 ──< Organization *

ENDPOINTS:
==========
- POST /api/v1/auth/register: Registro (crea Account + Organization + User)
- GET /api/v1/auth/me: Obtiene información del account
- PATCH /api/v1/accounts/{account_id}: Actualiza perfil de account (progresivo)

REGLA DE ORO:
=============
Los nombres NO son identidad. Los UUID sí.
❌ NO validar unicidad por account_name
❌ NO validar unicidad global por organization.name
✅ User.email debe ser único (global)
✅ Solo usuarios master/owner pueden modificar
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.account import AccountStatus
from app.utils.validators import validate_password

# =====================================================
# ONBOARDING SCHEMAS
# =====================================================


class OnboardingRequest(BaseModel):
    """
    Request para registro (POST /api/v1/auth/register).

    Campos mínimos obligatorios:
    - account_name: Nombre de la cuenta/empresa
    - email: Email del usuario master
    - password: Contraseña del usuario master

    Campos opcionales:
    - name: Nombre completo del usuario master (default: account_name)
    - organization_name: Nombre de la organización (default: "ORG " + account_name)
    - billing_email: Email de facturación (default: email del usuario)
    - country: Código de país ISO (ej: "MX", "US")
    - timezone: Zona horaria (ej: "America/Mexico_City")
    """

    account_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Nombre de la cuenta/empresa",
        json_schema_extra={"example": "Mi Empresa S.A."},
    )
    email: EmailStr = Field(
        ...,
        description="Email del usuario master (único dentro de la marca resuelta por Host, no globalmente)",
        json_schema_extra={"example": "usuario@ejemplo.com"},
    )
    password: str = Field(
        ...,
        min_length=8,
        description="Contraseña del usuario master",
    )

    # Campos opcionales
    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Nombre completo del usuario master. Si no se proporciona, usa account_name.",
        json_schema_extra={"example": "Juan Pérez"},
    )
    organization_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Nombre de la organización. Si no se proporciona, usa 'ORG ' + account_name.",
        json_schema_extra={"example": "Flota Norte"},
    )
    billing_email: Optional[EmailStr] = Field(
        None,
        description="Email de facturación. Si no se proporciona, usa el email del usuario.",
        json_schema_extra={"example": "facturacion@ejemplo.com"},
    )
    country: Optional[str] = Field(
        None,
        max_length=2,
        description="Código de país ISO 3166-1 alpha-2",
        json_schema_extra={"example": "MX"},
    )
    timezone: Optional[str] = Field(
        None,
        description="Zona horaria IANA",
        json_schema_extra={"example": "America/Mexico_City"},
    )

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        """Valida la contraseña usando el validador reutilizable."""
        return validate_password(v)

    @field_validator("account_name")
    @classmethod
    def validate_account_name(cls, v: str) -> str:
        """Valida el nombre de la cuenta (solo limpieza, NO unicidad)."""
        v = v.strip()
        if not v:
            raise ValueError("El nombre de la cuenta no puede estar vacío")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "account_name": "Transportes García S.A.",
                "email": "admin@transportesgarcia.com",
                "password": "SecureP@ssw0rd!",
                "name": "Carlos García López",
                "organization_name": "Flota Norte",
                "billing_email": "facturacion@transportesgarcia.com",
                "country": "MX",
                "timezone": "America/Mexico_City",
            }
        }


class OnboardingResponse(BaseModel):
    """
    Response del onboarding rápido.

    Retorna los IDs de las entidades creadas:
    - account_id: ID del Account creado
    - organization_id: ID de la Organization default
    - user_id: ID del User master
    """

    account_id: UUID = Field(..., description="ID del Account creado")
    organization_id: UUID = Field(..., description="ID de la Organization default")
    user_id: UUID = Field(..., description="ID del User master")

    class Config:
        json_schema_extra = {
            "example": {
                "account_id": "123e4567-e89b-12d3-a456-426614174000",
                "organization_id": "223e4567-e89b-12d3-a456-426614174001",
                "user_id": "323e4567-e89b-12d3-a456-426614174002",
            }
        }


# =====================================================
# ACCOUNT SCHEMAS
# =====================================================


class AccountBase(BaseModel):
    """Base para una cuenta."""

    name: str = Field(..., min_length=1, description="Nombre de la cuenta/empresa")


class AccountCreate(AccountBase):
    """Schema para crear una cuenta (uso interno)."""

    billing_email: Optional[EmailStr] = Field(None, description="Email de facturación")
    country: Optional[str] = Field(None, max_length=2, description="Código de país ISO")
    timezone: Optional[str] = Field(None, description="Zona horaria IANA")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Transportes García S.A.",
                "billing_email": "facturacion@transportesgarcia.com",
                "country": "MX",
                "timezone": "America/Mexico_City",
            }
        }


class AccountUpdate(BaseModel):
    """
    Schema para actualizar perfil de Account (PATCH /accounts/{id}).

    Todos los campos son opcionales para soportar perfil progresivo.
    Solo usuarios master/owner pueden usar este endpoint.

    ❌ NO se exigen campos fiscales
    ❌ NO se valida unicidad por nombre
    """

    account_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Nombre de la cuenta/empresa (puede repetirse)",
    )
    billing_email: Optional[EmailStr] = Field(
        None,
        description="Email de facturación",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "account_name": "Transportes García S.A. de C.V.",
                "billing_email": "nuevo-email@empresa.com",
            }
        }


class AccountOut(BaseModel):
    """
    Account en respuestas.

    Representa la información completa de un Account.
    """

    id: UUID
    account_name: str = Field(..., alias="name")
    status: AccountStatus
    billing_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "account_name": "Transportes García S.A.",
                "status": "ACTIVE",
                "billing_email": "facturacion@transportesgarcia.com",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
            }
        }


class AccountUpdateResponse(BaseModel):
    """
    Response del endpoint PATCH /accounts/{account_id}.

    Retorna la información actualizada del Account.
    """

    id: UUID
    account_name: str
    billing_email: Optional[str] = None
    updated_at: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "account_name": "Transportes García S.A. de C.V.",
                "billing_email": "facturacion@empresa.com",
                "updated_at": "2024-01-20T15:45:00Z",
            }
        }


class AuthMeResponse(BaseModel):
    """
    Response del endpoint GET /auth/me.

    Incluye información del Account y el rol del usuario.
    """

    account: AccountOut
    role: str = Field(..., description="Rol del usuario en su organización actual")
    organization_id: UUID = Field(..., description="ID de la organización actual")

    class Config:
        json_schema_extra = {
            "example": {
                "account": {
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "account_name": "Transportes García S.A.",
                    "status": "ACTIVE",
                    "billing_email": "facturacion@transportesgarcia.com",
                    "created_at": "2024-01-15T10:30:00Z",
                    "updated_at": "2024-01-15T10:30:00Z",
                },
                "role": "owner",
                "organization_id": "223e4567-e89b-12d3-a456-426614174001",
            }
        }


class AccountWithOrganizationsOut(AccountOut):
    """Cuenta con información adicional sobre sus organizaciones."""

    organizations_count: int = 0

    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "account_name": "Transportes García S.A.",
                "status": "ACTIVE",
                "billing_email": "facturacion@transportesgarcia.com",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
                "organizations_count": 1,
            }
        }

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.utils.validators import validate_name, validate_password


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    is_master: bool = False


class UserCreate(UserBase):
    client_id: Optional[UUID] = None
    name: str = Field(..., min_length=1, description="Nombre del usuario")
    password: str = Field(..., min_length=8, description="Contraseña del usuario")

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        """Valida la contraseña usando el validador reutilizable."""
        return validate_password(v)

    @field_validator("name")
    @classmethod
    def validate_name_field(cls, v: str) -> str:
        """Valida el nombre usando el validador reutilizable."""
        return validate_name(v)


class UserLogin(BaseModel):
    """Schema para la petición de login."""

    email: EmailStr = Field(..., description="Correo electrónico del usuario")
    password: str = Field(..., min_length=1, description="Contraseña del usuario")

    class Config:
        json_schema_extra = {
            "example": {"email": "usuario@example.com", "password": "MiPassword123!"}
        }


class UserLoginResponse(BaseModel):
    """Schema para la respuesta de login."""

    user: "UserOut"
    access_token: str
    id_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int

    class Config:
        json_schema_extra = {
            "example": {
                "user": {
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "email": "usuario@example.com",
                    "full_name": "Juan García",
                    "is_master": True,
                },
                "access_token": "eyJraWQiOiJ...",
                "id_token": "eyJraWQiOiJ...",
                "refresh_token": "eyJjdHkiOiJ...",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        }


class UserOut(UserBase):
    id: UUID
    client_id: UUID
    cognito_sub: Optional[str] = None
    email_verified: bool = False
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "client_id": "223e4567-e89b-12d3-a456-426614174000",
                "cognito_sub": "us-east-1:12345678-1234-1234-1234-123456789012",
                "email": "usuario@example.com",
                "full_name": "Juan García",
                "is_master": True,
                "email_verified": True,
                "last_login_at": "2024-01-15T10:30:00Z",
                "created_at": "2024-01-10T08:00:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
            }
        }


class UserInvite(BaseModel):
    """Schema para invitar un usuario."""

    email: EmailStr = Field(..., description="Correo electrónico del usuario a invitar")
    full_name: str = Field(..., min_length=1, description="Nombre completo del usuario")

    class Config:
        json_schema_extra = {
            "example": {"email": "invitado@ejemplo.com", "full_name": "Juan Pérez"}
        }


class UserInviteResponse(BaseModel):
    """Schema para la respuesta de invitación."""

    detail: str
    expires_at: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Invitación enviada a invitado@ejemplo.com",
                "expires_at": "2025-11-05T23:59:00",
            }
        }


class UserAcceptInvitation(BaseModel):
    """Schema para aceptar una invitación."""

    token: str = Field(..., description="Token de invitación")
    password: str = Field(..., min_length=8, description="Contraseña del usuario")

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        """Valida la contraseña usando el validador reutilizable."""
        return validate_password(v)

    class Config:
        json_schema_extra = {
            "example": {"token": "abc123-def456-ghi789", "password": "MiPassword123!"}
        }


class UserAcceptInvitationResponse(BaseModel):
    """Schema para la respuesta de aceptación de invitación."""

    detail: str
    user: UserOut

    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Usuario creado exitosamente.",
                "user": {
                    "id": "123e4567-e89b-12d3-a456-426614174000",
                    "client_id": "223e4567-e89b-12d3-a456-426614174000",
                    "email": "invitado@ejemplo.com",
                    "full_name": "Juan Pérez",
                    "is_master": False,
                    "email_verified": True,
                    "created_at": "2024-01-10T08:00:00Z",
                    "updated_at": "2024-01-10T08:00:00Z",
                },
            }
        }


class ForgotPasswordRequest(BaseModel):
    """Schema para solicitar recuperación de contraseña."""

    email: EmailStr = Field(..., description="Correo electrónico del usuario")

    class Config:
        json_schema_extra = {"example": {"email": "usuario@example.com"}}


class ForgotPasswordResponse(BaseModel):
    """Schema para la respuesta de solicitud de recuperación de contraseña."""

    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Se ha enviado un código de verificación al correo registrado."
            }
        }


class ResetPasswordRequest(BaseModel):
    """Schema para restablecer la contraseña."""

    email: EmailStr = Field(..., description="Correo electrónico del usuario")
    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Código de verificación de 6 dígitos",
    )
    new_password: str = Field(
        ..., min_length=8, description="Nueva contraseña del usuario"
    )

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        """Valida que el código sea numérico."""
        if not v.isdigit():
            raise ValueError("El código debe contener solo dígitos")
        return v

    @field_validator("new_password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        """Valida la contraseña usando el validador reutilizable."""
        return validate_password(v)

    class Config:
        json_schema_extra = {
            "example": {
                "email": "usuario@example.com",
                "code": "123456",
                "new_password": "NuevaPassword123!",
            }
        }


class ResetPasswordResponse(BaseModel):
    """Schema para la respuesta de restablecimiento de contraseña."""

    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Contraseña restablecida exitosamente. Ahora puede iniciar sesión con su nueva contraseña."
            }
        }


class ChangePasswordRequest(BaseModel):
    """Schema para cambiar contraseña de usuario autenticado."""

    old_password: str = Field(
        ..., min_length=1, description="Contraseña actual del usuario"
    )
    new_password: str = Field(
        ..., min_length=8, description="Nueva contraseña del usuario"
    )

    @field_validator("new_password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        """Valida la contraseña usando el validador reutilizable."""
        return validate_password(v)

    class Config:
        json_schema_extra = {
            "example": {
                "old_password": "MiPwdAnterior123",
                "new_password": "NuevoPwdFuerte456!",
            }
        }


class ChangePasswordResponse(BaseModel):
    """Schema para la respuesta de cambio de contraseña."""

    message: str

    class Config:
        json_schema_extra = {
            "example": {"message": "Contraseña actualizada exitosamente."}
        }


class ResendVerificationRequest(BaseModel):
    """Schema para reenviar verificación de email."""

    email: EmailStr = Field(..., description="Correo electrónico del usuario")

    class Config:
        json_schema_extra = {"example": {"email": "usuario@example.com"}}


class ResendVerificationResponse(BaseModel):
    """Schema para la respuesta de reenvío de verificación."""

    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Si la cuenta existe, se ha reenviado el correo de verificación."
            }
        }


class ConfirmEmailRequest(BaseModel):
    """Schema para confirmar email con token."""

    token: str = Field(..., description="Token de verificación de email")

    class Config:
        json_schema_extra = {"example": {"token": "abc123-def456-ghi789"}}


class ConfirmEmailResponse(BaseModel):
    """Schema para la respuesta de confirmación de email."""

    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Email verificado exitosamente. Ahora puede iniciar sesión."
            }
        }


class ResendInvitationRequest(BaseModel):
    """Schema para reenviar invitación a un usuario."""

    email: EmailStr = Field(..., description="Correo electrónico del usuario invitado")

    class Config:
        json_schema_extra = {"example": {"email": "invitado@ejemplo.com"}}


class ResendInvitationResponse(BaseModel):
    """Schema para la respuesta de reenvío de invitación."""

    message: str
    expires_at: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Invitación reenviada a invitado@ejemplo.com",
                "expires_at": "2025-11-07T23:59:00",
            }
        }


class LogoutResponse(BaseModel):
    """Schema para la respuesta de logout."""

    message: str

    class Config:
        json_schema_extra = {"example": {"message": "Sesión cerrada exitosamente."}}


class RefreshTokenRequest(BaseModel):
    """Schema para la petición de refresh token."""

    email: EmailStr = Field(..., description="Correo electrónico del usuario")
    refresh_token: str = Field(..., description="Refresh token obtenido en el login")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "usuario@example.com",
                "refresh_token": "eyJjdHkiOiJ...",
            }
        }


class RefreshTokenResponse(BaseModel):
    """Schema para la respuesta de refresh token."""

    access_token: str
    id_token: str
    token_type: str = "Bearer"
    expires_in: int

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJraWQiOiJ...",
                "id_token": "eyJraWQiOiJ...",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        }


class InternalTokenRequest(BaseModel):
    """Schema para solicitar un token interno PASETO."""

    service: str = Field(..., description="Nombre del servicio (ej: 'gac')")
    role: str = Field(..., description="Rol del servicio (ej: 'GAC_ADMIN')")
    expires_in_hours: int = Field(
        default=24, ge=1, le=720, description="Horas de validez del token (1-720)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "service": "gac",
                "role": "GAC_ADMIN",
                "expires_in_hours": 24,
            }
        }


class InternalTokenResponse(BaseModel):
    """Schema para la respuesta del token interno PASETO."""

    token: str = Field(..., description="Token PASETO generado")
    expires_at: datetime = Field(..., description="Fecha de expiración del token")
    token_type: str = Field(default="Bearer", description="Tipo de token")

    class Config:
        json_schema_extra = {
            "example": {
                "token": "v4.local.xxx...",
                "expires_at": "2024-01-16T10:30:00Z",
                "token_type": "Bearer",
            }
        }

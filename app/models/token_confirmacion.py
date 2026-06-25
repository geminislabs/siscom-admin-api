import enum
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Relationship, SQLModel

from app.utils.datetime import utcnow

if TYPE_CHECKING:
    from app.models.user import User


class TokenType(str, enum.Enum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"
    INVITATION = "invitation"


class TokenConfirmacion(SQLModel, table=True):
    __tablename__ = "tokens_confirmacion"

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    token: str = Field(
        sa_column=Column(String, unique=True, nullable=False, index=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(
            DateTime,
            default=lambda: utcnow() + timedelta(hours=1),
            nullable=False,
        )
    )
    used: bool = Field(sa_column=Column(Boolean, default=False, nullable=False))
    type: TokenType = Field(
        sa_column=Column(
            String, default=TokenType.EMAIL_VERIFICATION.value, nullable=False
        )
    )
    user_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    # Campos adicionales para invitaciones
    email: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    full_name: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    organization_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    # Contraseña temporal (solo para EMAIL_VERIFICATION)
    password_temp: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )

    created_at: datetime = Field(
        sa_column=Column(
            TIMESTAMP(timezone=True), server_default=text("NOW()"), nullable=False
        )
    )

    # Relationships
    user: "User" = Relationship(back_populates="tokens")

    # Alias para compatibilidad (DEPRECATED)
    @property
    def client_id(self) -> Optional[UUID]:
        """DEPRECATED: Usar organization_id"""
        return self.organization_id

    @client_id.setter
    def client_id(self, value: Optional[UUID]):
        """DEPRECATED: Usar organization_id"""
        self.organization_id = value

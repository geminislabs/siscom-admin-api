"""
Modelo para roles a nivel de Account.

Define la relación entre usuarios y accounts con roles específicos.
Similar a OrganizationUser pero a nivel de cuenta comercial.

Basado en DDL: public.account_users
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.user import User


class AccountRole(str, enum.Enum):
    """
    Roles disponibles a nivel de Account.

    - owner: Control total del account, único por account
    - admin: Gestión administrativa del account
    - billing: Pagos, suscripciones, facturación a nivel account
    - member: Acceso básico al account
    """

    OWNER = "owner"
    ADMIN = "admin"
    BILLING = "billing"
    MEMBER = "member"


class AccountUser(SQLModel, table=True):
    """
    Relación usuario-account con rol asignado.

    Un usuario puede pertenecer a un account con un rol específico.
    Este modelo define permisos a nivel comercial/billing.
    """

    __tablename__ = "account_users"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "user_id", name="account_users_account_id_user_id_key"
        ),
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        ),
    )
    account_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    user_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    role: str = Field(
        default=AccountRole.MEMBER.value,
        sa_column=Column(
            String,
            nullable=False,
            default=AccountRole.MEMBER.value,
        ),
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )

    # Relationships
    account: "Account" = Relationship(back_populates="account_users")
    user: "User" = Relationship(back_populates="account_memberships")

    def is_owner(self) -> bool:
        """Verifica si es el owner del account."""
        return self.role == AccountRole.OWNER.value

    def can_manage_billing(self) -> bool:
        """Verifica si el rol puede gestionar facturación."""
        return self.role in [AccountRole.OWNER.value, AccountRole.BILLING.value]

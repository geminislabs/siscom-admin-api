"""
Modelo de Account - Raíz comercial del cliente.

Account SIEMPRE existe desde el primer registro.
Representa la entidad comercial/billing del cliente.

Modelo Conceptual:
    Account = Raíz comercial (billing, facturación)
    Organization = Raíz operativa (permisos, uso diario)

Relación: Account 1 ──< Organization *

En el onboarding rápido (POST /clients):
    1. Se crea Account (name = account_name del input)
    2. Se crea Organization default (pertenece a Account)
    3. Se crea User master (owner de Organization)
    4. Se registra usuario en Cognito

REGLA DE ORO: Los nombres NO son identidad. Los UUID sí.
Los nombres pueden repetirse; la unicidad está en los UUIDs.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import Column, DateTime, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.account_user import AccountUser
    from app.models.organization import Organization


class AccountStatus(str, enum.Enum):
    """
    Estados de una cuenta.

    - ACTIVE: Cuenta activa y operativa
    - SUSPENDED: Cuenta suspendida (falta de pago, violación TOS)
    - DELETED: Eliminación lógica
    """

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class Account(SQLModel, table=True):
    """
    Modelo de Account (tabla: accounts).

    Representa la raíz comercial del cliente.
    Cada Account puede tener múltiples Organizations.

    Responsabilidades:
    - Billing y facturación
    - Agregación comercial
    - Información fiscal y de contacto
    - Auditoría a nivel cuenta (account_events)

    NO gobierna:
    - Permisos operativos (eso es Organization)
    - Dispositivos, unidades, usuarios (eso es Organization)

    NOTA: El campo 'name' puede repetirse entre accounts.
    La unicidad está en el UUID, no en el nombre.
    """

    __tablename__ = "accounts"

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    name: str = Field(sa_column=Column("account_name", Text, nullable=False))
    status: AccountStatus = Field(
        default=AccountStatus.ACTIVE,
        sa_column=Column(Text, default=AccountStatus.ACTIVE.value, nullable=False),
    )
    billing_email: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        )
    )

    # Relationships
    organizations: List["Organization"] = Relationship(back_populates="account")
    account_users: List["AccountUser"] = Relationship(back_populates="account")

    def get_default_organization(self) -> Optional["Organization"]:
        """
        Obtiene la organización default de la cuenta.

        Por ahora retorna la primera organización.
        En el futuro podría haber un campo `is_default`.
        """
        if self.organizations:
            return self.organizations[0]
        return None

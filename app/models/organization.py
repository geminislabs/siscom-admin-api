"""
Modelo de Organization - Raíz operativa del cliente.

Organization SIEMPRE pertenece a un Account.
Gobierna todo lo operativo: permisos, dispositivos, usuarios, suscripciones.

Modelo Conceptual:
    Account = Raíz comercial (billing, facturación)
    Organization = Raíz operativa (permisos, uso diario)

Relación: Account 1 ──< Organization *

REGLA DE ORO:
=============
Los nombres NO son identidad. Los UUID sí.
- Organization.name puede repetirse globalmente
- Organization.name único solo dentro del mismo account (account_id + name)

Las suscripciones activas se calculan dinámicamente.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Relationship, SQLModel

from app.utils.datetime import utcnow

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.capability import OrganizationCapability
    from app.models.device import Device
    from app.models.order import Order
    from app.models.organization_user import OrganizationUser
    from app.models.subscription import Subscription
    from app.models.unit import Unit
    from app.models.user import User


class OrganizationStatus(str, enum.Enum):
    """
    Estados de una organización.

    - PENDING: Pendiente de verificación de email
    - ACTIVE: Organización activa y operativa
    - SUSPENDED: Organización suspendida (puede ser por falta de pago, violación TOS, etc.)
    - DELETED: Eliminación lógica
    """

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class Organization(SQLModel, table=True):
    """
    Modelo de Organization (tabla: organizations).

    Representa una organización/empresa cliente del sistema.
    Cada organización pertenece a un Account y puede tener:
    - Múltiples usuarios con diferentes roles
    - Múltiples suscripciones (activas, históricas)
    - Overrides de capabilities específicos
    - Dispositivos, unidades, etc.
    """

    __tablename__ = "organizations"

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )

    # FK a Account - SIEMPRE existe
    account_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    name: str = Field(sa_column=Column(Text, nullable=False))
    status: OrganizationStatus = Field(
        default=OrganizationStatus.ACTIVE,
        sa_column=Column(Text, default=OrganizationStatus.ACTIVE.value, nullable=True),
    )

    # Campos adicionales
    billing_email: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    country: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    timezone: str = Field(
        default="UTC", sa_column=Column(Text, default="UTC", nullable=True)
    )
    org_metadata: Optional[dict] = Field(
        default=None,
        sa_column=Column(
            "metadata", JSONB, server_default=text("'{}'::jsonb"), nullable=True
        ),
    )

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, server_default=text("now()"), nullable=True),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, server_default=text("now()"), nullable=True),
    )

    # Relationships
    account: "Account" = Relationship(back_populates="organizations")
    users: List["User"] = Relationship(back_populates="organization")
    devices: List["Device"] = Relationship(back_populates="organization")
    units: List["Unit"] = Relationship(back_populates="organization")
    subscriptions: List["Subscription"] = Relationship(
        back_populates="organization",
        sa_relationship_kwargs={"foreign_keys": "[Subscription.organization_id]"},
    )
    orders: List["Order"] = Relationship(back_populates="organization")
    organization_users: List["OrganizationUser"] = Relationship(
        back_populates="organization"
    )
    organization_capabilities: List["OrganizationCapability"] = Relationship(
        back_populates="organization"
    )

    def get_active_subscriptions(self) -> list["Subscription"]:
        """
        Obtiene las suscripciones activas de la organización.

        Una suscripción está activa si:
        - status = ACTIVE o TRIAL
        - expires_at > now() o expires_at is NULL
        """
        from app.models.subscription import SubscriptionStatus

        now = utcnow()
        return [
            sub
            for sub in self.subscriptions
            if sub.status in [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]
            and (sub.expires_at is None or sub.expires_at > now)
        ]

    def has_active_subscription(self) -> bool:
        """Verifica si la organización tiene al menos una suscripción activa."""
        return len(self.get_active_subscriptions()) > 0

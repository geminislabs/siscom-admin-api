"""
Modelo de Suscripción.

Una organización puede tener MÚLTIPLES suscripciones:
- Activas (ACTIVE, TRIAL)
- Históricas (CANCELLED, EXPIRED)

La suscripción activa se CALCULA dinámicamente, no es un campo fijo.

Relación:
- Subscription pertenece a Organization (operativo)
- Organization pertenece a Account (comercial)
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, Relationship, SQLModel

from app.utils.datetime import utcnow

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.plan import Plan


class SubscriptionStatus(str, enum.Enum):
    """
    Estados de una suscripción.

    - ACTIVE: Suscripción vigente y operativa
    - TRIAL: Período de prueba
    - CANCELLED: Cancelada por el usuario/sistema
    - EXPIRED: Venció sin renovación
    """

    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    TRIAL = "TRIAL"


class BillingCycle(str, enum.Enum):
    """Ciclos de facturación disponibles."""

    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class Subscription(SQLModel, table=True):
    """
    Suscripción de una organización a un plan.

    Una organización puede tener múltiples suscripciones en diferentes estados.
    Las suscripciones activas determinan las capabilities disponibles.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("idx_subscriptions_organization", "organization_id"),
        Index("idx_subscriptions_status", "status"),
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    # NOTA: La columna en BD puede llamarse account_id (legacy) pero representa organization_id
    organization_id: UUID = Field(
        sa_column=Column(
            "organization_id",  # Nombre de columna en BD
            PGUUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    plan_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("plans.id"),
            nullable=False,
        ),
    )
    status: SubscriptionStatus = Field(
        sa_column=Column(Text, default=SubscriptionStatus.ACTIVE.value, nullable=False)
    )
    started_at: datetime = Field(
        sa_column=Column(DateTime, server_default=text("now()"), nullable=False)
    )
    expires_at: datetime = Field(sa_column=Column(DateTime, nullable=False))
    cancelled_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    renewed_from: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    auto_renew: bool = Field(
        default=True, sa_column=Column(Boolean, default=True, nullable=True)
    )

    # Campos adicionales
    external_id: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
        description="ID externo (ej: Stripe subscription ID)",
    )
    billing_cycle: str = Field(
        default=BillingCycle.MONTHLY.value,
        sa_column=Column(Text, default="MONTHLY", nullable=True),
    )
    current_period_start: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    current_period_end: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    active_units: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1")),
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
    organization: "Organization" = Relationship(
        back_populates="subscriptions",
        sa_relationship_kwargs={"foreign_keys": "[Subscription.organization_id]"},
    )
    plan: "Plan" = Relationship(back_populates="subscriptions")

    # Alias para compatibilidad (DEPRECATED)
    @property
    def client_id(self) -> UUID:
        """DEPRECATED: Usar organization_id"""
        return self.organization_id

    @client_id.setter
    def client_id(self, value: UUID):
        """DEPRECATED: Usar organization_id"""
        self.organization_id = value

    @property
    def client(self) -> "Organization":
        """DEPRECATED: Usar organization"""
        return self.organization

    def is_active(self) -> bool:
        """Verifica si la suscripción está activa."""
        if self.status not in [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]:
            return False
        if self.expires_at and self.expires_at < utcnow():
            return False
        return True

    def days_until_expiration(self) -> Optional[int]:
        """Retorna días hasta la expiración, o None si no expira."""
        if not self.expires_at:
            return None
        delta = self.expires_at - utcnow()
        return max(0, delta.days)

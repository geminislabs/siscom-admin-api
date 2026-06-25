"""
⚠️ MODELO LEGACY - NO USAR EN CÓDIGO NUEVO ⚠️

Este modelo fue diseñado para un sistema de servicios por dispositivo.
El modelo actual de negocio usa Subscriptions a nivel de organización.

MIGRACIÓN FUTURA:
- Los device_services activos deberán convertirse en Subscriptions
- Este modelo será eliminado cuando se complete la migración
- Los endpoints /services/* se mantienen por compatibilidad temporal

Para código nuevo, usar:
- app.models.subscription.Subscription
- app.services.subscription_query

NOTA: La tabla device_services puede no existir en la BD.
Este modelo se mantiene solo por compatibilidad con endpoints legacy.
"""

import enum
import warnings
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, Relationship, SQLModel

from app.utils.datetime import utcnow

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.plan import Plan

# Emitir warning al importar este módulo
warnings.warn(
    "DeviceService es un modelo LEGACY. "
    "Para código nuevo, usar Subscription y subscription_query.",
    DeprecationWarning,
    stacklevel=2,
)


class SubscriptionType(str, enum.Enum):
    """LEGACY: Tipos de suscripción por dispositivo."""

    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class DeviceServiceStatus(str, enum.Enum):
    """LEGACY: Estados de servicio por dispositivo."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DeviceService(SQLModel, table=True):
    """
    ⚠️ LEGACY MODEL ⚠️

    Servicio de rastreo por dispositivo.

    DEPRECATED: El modelo actual usa Subscriptions a nivel de Organization.
    Este modelo se mantiene solo por compatibilidad con endpoints /services/*.

    NO USAR EN CÓDIGO NUEVO.
    """

    __tablename__ = "device_services"
    __table_args__ = (
        Index("idx_device_services_device", "device_id"),
        Index("idx_device_services_client", "client_id"),
        Index("idx_device_services_status", "status"),
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    # device_id referencia a devices.device_id (TEXT)
    device_id: str = Field(
        sa_column=Column(
            Text,
            ForeignKey("devices.device_id"),
            nullable=False,
        ),
    )
    # LEGACY: Mantiene client_id por compatibilidad con esquema existente
    client_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("organizations.id"),  # Apunta a organizations ahora
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
    subscription_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True
        ),
    )
    subscription_type: SubscriptionType = Field(
        sa_column=Column(String, nullable=False)
    )
    status: DeviceServiceStatus = Field(
        sa_column=Column(
            String, default=DeviceServiceStatus.ACTIVE.value, nullable=False
        )
    )
    activated_at: datetime = Field(
        sa_column=Column(DateTime, default=utcnow, nullable=False)
    )
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    renewed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    cancelled_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )
    auto_renew: bool = Field(sa_column=Column(Boolean, default=True, nullable=False))
    payment_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True), ForeignKey("payments.id"), nullable=True
        ),
    )

    created_at: datetime = Field(
        sa_column=Column(DateTime, default=utcnow, nullable=False)
    )

    # Relationships
    device: "Device" = Relationship(back_populates="device_services")
    plan: "Plan" = Relationship(back_populates="device_services")

"""
Modelo de AccountEvent - Auditoría de acciones.

Registra todas las acciones relevantes realizadas en el contexto
de una cuenta y sus organizaciones.

Tabla: account_events
"""

import enum
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Column, DateTime, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel


class ActorType(str, enum.Enum):
    """Tipo de actor que realizó la acción."""

    USER = "user"
    SYSTEM = "system"
    SERVICE = "service"
    API = "api"


class EventType(str, enum.Enum):
    """Tipos de eventos de auditoría."""

    # Organization Users
    ORG_USER_ADDED = "org_user_added"
    ORG_USER_REMOVED = "org_user_removed"
    ORG_USER_ROLE_CHANGED = "org_user_role_changed"
    ORG_USER_STATUS_CHANGED = "org_user_status_changed"

    # Organization Capabilities
    ORG_CAPABILITY_CREATED = "org_capability_created"
    ORG_CAPABILITY_UPDATED = "org_capability_updated"
    ORG_CAPABILITY_DELETED = "org_capability_deleted"

    # Organization
    ORG_CREATED = "org_created"
    ORG_UPDATED = "org_updated"
    ORG_STATUS_CHANGED = "org_status_changed"

    # Account
    ACCOUNT_CREATED = "account_created"
    ACCOUNT_UPDATED = "account_updated"


class TargetType(str, enum.Enum):
    """Tipo de entidad objetivo de la acción."""

    ORGANIZATION_USER = "organization_user"
    ORGANIZATION_CAPABILITY = "organization_capability"
    ORGANIZATION = "organization"
    USER = "user"
    ACCOUNT = "account"
    CAPABILITY = "capability"


class AccountEvent(SQLModel, table=True):
    """
    Modelo de evento de auditoría (tabla: account_events).

    Registra acciones realizadas dentro de una cuenta/organización
    para auditoría y trazabilidad.

    Campos:
    - account_id: Cuenta donde ocurrió el evento
    - organization_id: Organización (si aplica)
    - actor_user_id: Usuario que realizó la acción (si aplica)
    - actor_type: Tipo de actor (user, system, service, api)
    - event_type: Tipo de evento (ej: org_user_added)
    - target_type: Tipo de entidad afectada
    - target_id: ID de la entidad afectada
    - metadata: Información adicional del evento (JSONB)
    - ip_address: IP del actor (si aplica)
    - user_agent: User agent del actor (si aplica)
    """

    __tablename__ = "account_events"

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )

    account_id: UUID = Field(sa_column=Column(PGUUID(as_uuid=True), nullable=False))

    organization_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(PGUUID(as_uuid=True), nullable=True),
    )

    actor_user_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(PGUUID(as_uuid=True), nullable=True),
    )

    actor_type: str = Field(sa_column=Column(Text, nullable=False))

    event_type: str = Field(sa_column=Column(Text, nullable=False))

    target_type: str = Field(sa_column=Column(Text, nullable=False))

    target_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(PGUUID(as_uuid=True), nullable=True),
    )

    event_metadata: Optional[dict] = Field(
        default=None,
        sa_column=Column("metadata", JSONB, nullable=True),
    )

    ip_address: Optional[str] = Field(
        default=None,
        sa_column=Column(INET, nullable=True),
    )

    user_agent: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=text("now()"),
            nullable=False,
        )
    )

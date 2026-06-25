"""
Modelos para el sistema de Capabilities.

Las capabilities definen los límites y features disponibles para una organización.
Se resuelven con la regla: organization_override ?? plan_capability ?? default

Basado en DDL:
- public.capabilities
- public.plan_capabilities
- public.organization_capabilities
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Relationship, SQLModel

from app.utils.datetime import utcnow

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.plan import Plan


class CapabilityValueType(str, enum.Enum):
    """Tipos de valor que puede tener una capability."""

    INT = "int"
    BOOL = "bool"
    TEXT = "text"


class Capability(SQLModel, table=True):
    """
    Definición de una capability del sistema.

    Ejemplo: max_devices, max_geofences, ai_features_enabled
    """

    __tablename__ = "capabilities"

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    code: str = Field(sa_column=Column(Text, unique=True, nullable=False))
    description: str = Field(sa_column=Column(Text, nullable=False))
    value_type: str = Field(sa_column=Column(Text, nullable=False))
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=True
        ),
    )

    # Relationships
    plan_capabilities: List["PlanCapability"] = Relationship(
        back_populates="capability"
    )
    organization_capabilities: List["OrganizationCapability"] = Relationship(
        back_populates="capability"
    )


class PlanCapability(SQLModel, table=True):
    """
    Valor de una capability para un plan específico.

    Define qué capabilities incluye cada plan y con qué valores.
    """

    __tablename__ = "plan_capabilities"

    plan_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("plans.id"),
            primary_key=True,
            nullable=False,
        )
    )
    capability_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("capabilities.id"),
            primary_key=True,
            nullable=False,
        )
    )
    value_int: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    value_bool: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    value_text: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # Relationships
    plan: "Plan" = Relationship(back_populates="plan_capabilities")
    capability: Capability = Relationship(back_populates="plan_capabilities")

    def get_value(self):
        """Retorna el valor según el tipo."""
        if self.value_int is not None:
            return self.value_int
        if self.value_bool is not None:
            return self.value_bool
        if self.value_text is not None:
            return self.value_text
        return None


class OrganizationCapability(SQLModel, table=True):
    """
    Override de capability para una organización específica.

    Permite que una organización tenga valores diferentes a los de su plan.
    Por ejemplo: promociones, acuerdos especiales, ajustes temporales.
    """

    __tablename__ = "organization_capabilities"

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    organization_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("organizations.id"),
            nullable=False,
        )
    )
    capability_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("capabilities.id"),
            nullable=False,
        )
    )
    value_int: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    value_bool: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    value_text: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # Relationships
    organization: "Organization" = Relationship(
        back_populates="organization_capabilities"
    )
    capability: Capability = Relationship(back_populates="organization_capabilities")

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

    def get_value(self):
        """Retorna el valor según el tipo."""
        if self.value_int is not None:
            return self.value_int
        if self.value_bool is not None:
            return self.value_bool
        if self.value_text is not None:
            return self.value_text
        return None

    def is_expired(self) -> bool:
        """Verifica si el override ha expirado."""
        if self.expires_at is None:
            return False
        return utcnow() > self.expires_at

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

from app.utils.datetime import as_naive_utc, utcnow

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
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )

    # Relationships
    plan_capabilities: List["PlanCapability"] = Relationship(
        back_populates="capability"
    )
    organization_capabilities: List["OrganizationCapability"] = Relationship(
        back_populates="capability"
    )
    account_capabilities: List["AccountCapability"] = Relationship(
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
        """
        Si el override ha expirado.

        `expires_at` es TIMESTAMP WITH TIME ZONE —la columna la anade la
        migracion 026— y `utcnow()` devuelve naive a proposito, asi que
        compararlas sin normalizar lanza
        `TypeError: can't compare offset-naive and offset-aware datetimes`.
        Es el mismo fallo que tenia `Subscription.is_active()`, en el camino
        central de resolucion de capabilities: cualquier override con fecha de
        caducidad reventaba la peticion entera. No se habia visto porque la
        columna es de ayer y todavia no hay filas que la usen.
        """
        expira = as_naive_utc(self.expires_at)
        if expira is None:
            return False
        return utcnow() > expira


class AccountCapability(SQLModel, table=True):
    """
    Límite **comercial** de una cuenta (tabla: account_capabilities).

    Es el segundo nivel de §4. `organization_capabilities` guarda límites
    operativos —cuántos dispositivos, cuántas geocercas—; esta tabla guarda lo
    que la cuenta puede hacer como negocio: revender, tener dominio propio,
    cuántas subcuentas.

    POR QUÉ HACEN FALTA LOS DOS NIVELES
    ===================================
    Si todo viviera en `Organization`, un revendedor con miles de hijos no
    tendría dónde guardar «puedes tener 3 dominios y 5 000 subcuentas»: habría
    que elegir arbitrariamente una de sus Organizations como la «buena», y esa
    fila mágica termina causando un bug.

    DOS RESTRICCIONES QUE `OrganizationCapability` NO TIENE
    ======================================================
    - `UNIQUE (account_id, capability_id)` — sin ella caben dos overrides que
      se contradicen sobre la misma capability, que es lo que admite hoy la
      tabla de organización.
    - `CHECK num_nonnulls(...) = 1` — exactamente un valor, nunca cero ni dos.

    La resolución con techo descendente vive en
    `app.services.account_capabilities`, no aquí.
    """

    __tablename__ = "account_capabilities"

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    account_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("accounts.id", ondelete="CASCADE"),
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
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )

    # Relationships
    capability: Capability = Relationship(back_populates="account_capabilities")

    def get_value(self):
        """
        El valor de esta fila, sea del tipo que sea.

        No usa `if value_x is not None` en cascada por casualidad: `value_bool`
        vale `False` legítimamente, y una comprobación por veracidad lo tomaría
        por ausente. Es la trampa de §17 —«vacío no es sin límite»— en su forma
        más pequeña: sobre una capability booleana, confundir `False` con «no
        hay valor» convierte un permiso denegado en uno heredado.
        """
        if self.value_int is not None:
            return self.value_int
        if self.value_bool is not None:
            return self.value_bool
        if self.value_text is not None:
            return self.value_text
        return None

    def is_expired(self) -> bool:
        """
        Si el límite ya caducó. Un límite caducado no restringe ni concede.

        Normaliza antes de comparar por la misma razón que
        `OrganizationCapability.is_expired()`: la columna es `timestamptz` y
        `utcnow()` es naive.
        """
        expira = as_naive_utc(self.expires_at)
        if expira is None:
            return False
        return utcnow() > expira

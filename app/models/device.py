from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, Relationship, SQLModel

from app.utils.datetime import utcnow

if TYPE_CHECKING:
    from app.models.device_service import DeviceService
    from app.models.organization import Organization
    from app.models.sim_card import SimCard
    from app.models.unit_device import UnitDevice
    from app.models.user import User


class Device(SQLModel, table=True):
    """
    Modelo de dispositivos GPS/telemetría.

    Estados del ciclo de vida:
    - nuevo: Recién ingresado al inventario
    - preparado: Asignado a un cliente, listo para envío
    - enviado: En camino al cliente
    - entregado: Recibido por el cliente
    - asignado: Vinculado a una unidad (vehículo)
    - devuelto: Devuelto al inventario
    - inactivo: Fuera de uso o dado de baja
    """

    __tablename__ = "devices"
    __table_args__ = (
        Index("idx_devices_status", "status"),
        Index("idx_devices_organization_id", "organization_id"),
        Index("idx_devices_brand_model", "brand", "model"),
        CheckConstraint(
            "status IN ('nuevo', 'preparado', 'enviado', 'entregado', 'asignado', 'devuelto', 'inactivo')",
            name="check_device_status",
        ),
    )

    # device_id es ahora PRIMARY KEY
    device_id: str = Field(sa_column=Column(Text, primary_key=True))

    brand: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    model: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    firmware_version: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # organization_id ahora es nullable (se asigna al enviar)
    organization_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    status: str = Field(
        default="nuevo", sa_column=Column(Text, nullable=False, server_default="nuevo")
    )

    last_comm_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True), nullable=True)
    )

    created_at: datetime = Field(
        sa_column=Column(
            TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            TIMESTAMP(timezone=True),
            server_default=text("now()"),
            onupdate=utcnow,
            nullable=False,
        )
    )
    last_assignment_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True), nullable=True)
    )

    notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # Relationships
    organization: Optional["Organization"] = Relationship(back_populates="devices")
    device_services: List["DeviceService"] = Relationship(back_populates="device")
    device_events: List["DeviceEvent"] = Relationship(
        back_populates="device",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    unit_devices: List["UnitDevice"] = Relationship(
        back_populates="device",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    sim_card: Optional["SimCard"] = Relationship(
        back_populates="device",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "uselist": False},
    )

    # Alias para compatibilidad (DEPRECATED)
    @property
    def client_id(self) -> Optional[UUID]:
        """DEPRECATED: Usar organization_id"""
        return self.organization_id

    @client_id.setter
    def client_id(self, value: Optional[UUID]):
        """DEPRECATED: Usar organization_id"""
        self.organization_id = value

    @property
    def client(self) -> Optional["Organization"]:
        """DEPRECATED: Usar organization"""
        return self.organization


class DeviceEvent(SQLModel, table=True):
    """
    Historial de eventos y cambios de estado de dispositivos.

    Tipos de eventos:
    - creado: Dispositivo registrado en el sistema
    - preparado: Dispositivo asignado a cliente y listo para envío
    - enviado: Dispositivo enviado al cliente
    - entregado: Dispositivo recibido por el cliente
    - asignado: Dispositivo asignado a una unidad
    - devuelto: Dispositivo devuelto al inventario
    - firmware_actualizado: Actualización de firmware
    - nota: Nota administrativa
    - estado_cambiado: Cambio de estado genérico
    """

    __tablename__ = "device_events"
    __table_args__ = (
        Index("idx_device_events_device_id", "device_id"),
        Index("idx_device_events_created_at", "created_at"),
        Index("idx_device_events_event_type", "event_type"),
        CheckConstraint(
            "event_type IN ('creado', 'preparado', 'enviado', 'entregado', 'asignado', 'devuelto', 'firmware_actualizado', 'nota', 'estado_cambiado')",
            name="check_event_type",
        ),
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )

    device_id: str = Field(
        sa_column=Column(
            Text, ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False
        )
    )

    event_type: str = Field(sa_column=Column(Text, nullable=False))
    old_status: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    new_status: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    performed_by: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    event_details: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    created_at: datetime = Field(
        sa_column=Column(
            TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
        )
    )

    # Relationships
    device: "Device" = Relationship(back_populates="device_events")
    user: Optional["User"] = Relationship()

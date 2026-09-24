from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Column, Float, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, SQLModel

if TYPE_CHECKING:
    pass


class Trip(SQLModel, table=True):
    """
    Modelo de lectura para trips (viajes).
    Los datos son escritos por el servicio siscom-trips.
    Este servicio (siscom-admin-api) solo lee.
    """

    __tablename__ = "trips"
    __table_args__ = (
        Index("idx_trips_device_start", "device_id", "start_time"),
        Index("idx_trips_start_time", "start_time"),
    )

    trip_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
        )
    )

    device_id: str = Field(
        sa_column=Column(
            String(20),
            ForeignKey("devices.device_id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    start_time: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), nullable=False)
    )

    # Un viaje en curso no tiene fin. La base siempre lo admitio y el modelo
    # decia lo contrario; en produccion hay cuatro asi.
    end_time: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True), nullable=True)
    )

    start_lat: Optional[float] = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    start_lng: Optional[float] = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    end_lat: Optional[float] = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    end_lng: Optional[float] = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )

    distance_meters: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True), server_default=text("now()"), nullable=True
        ),
    )


class TripPoint(SQLModel, table=True):
    """
    Modelo de lectura para puntos GPS de un trip.
    Los datos son escritos por el servicio siscom-trips.
    """

    __tablename__ = "trip_points"
    __table_args__ = (
        Index("idx_trip_points_device_time", "device_id", "timestamp"),
        Index("idx_trip_points_time", "timestamp"),
        Index("trip_points_timestamp_idx", "timestamp"),
    )

    point_id: int = Field(
        sa_column=Column(Integer, primary_key=True, autoincrement=True)
    )

    trip_id: UUID = Field(sa_column=Column(PGUUID(as_uuid=True), nullable=False))

    device_id: str = Field(sa_column=Column(String, nullable=False))

    timestamp: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), nullable=False)
    )

    lat: float = Field(sa_column=Column(Float, nullable=False))
    lng: float = Field(sa_column=Column(Float, nullable=False))

    speed: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    heading: Optional[float] = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )

    correlation_id: UUID = Field(sa_column=Column(PGUUID(as_uuid=True), nullable=False))


class TripAlert(SQLModel, table=True):
    """
    Modelo de lectura para alertas de un trip.
    Los datos son escritos por el servicio siscom-trips.
    Tabla particionada por TIMESTAMP.
    """

    __tablename__ = "trip_alerts"
    __table_args__ = (
        Index("idx_trip_alert_device", "device_id"),
        Index("idx_trip_alert_trip", "trip_id"),
        Index("idx_trip_alerts_device_time", "device_id", "timestamp"),
        Index("idx_trip_alerts_type", "alert_type"),
    )

    alert_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
        )
    )

    trip_id: UUID = Field(sa_column=Column(PGUUID(as_uuid=True), nullable=False))

    device_id: str = Field(sa_column=Column(String, nullable=False))

    timestamp: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), nullable=False)
    )

    lat: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    lon: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))

    alert_type: str = Field(sa_column=Column(String, nullable=False))

    raw_code: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )

    severity: Optional[int] = Field(
        default=1, sa_column=Column(Integer, nullable=True, server_default="1")
    )

    alert_metadata: Optional[dict] = Field(
        default=None, sa_column=Column("metadata", JSONB, nullable=True)
    )

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True), server_default=text("now()"), nullable=True
        ),
    )

    correlation_id: Optional[UUID] = Field(
        default=None, sa_column=Column(PGUUID(as_uuid=True), nullable=True)
    )


class TripEvent(SQLModel, table=True):
    """
    Modelo de lectura para eventos de un trip.
    Los datos son escritos por el servicio siscom-trips.

    Nota: Este modelo se infiere de la estructura mencionada en el contexto
    ya que no se proporcionó el DDL explícito.
    """

    __tablename__ = "trip_events"

    event_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
        )
    )

    trip_id: UUID = Field(sa_column=Column(PGUUID(as_uuid=True), nullable=False))

    device_id: str = Field(sa_column=Column(String, nullable=False))

    timestamp: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), nullable=False)
    )

    event_type: str = Field(sa_column=Column(String, nullable=False))

    value: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True), server_default=text("now()"), nullable=True
        ),
    )

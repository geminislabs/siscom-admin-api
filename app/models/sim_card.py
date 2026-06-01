from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Column, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.sim_kore_profile import SimKoreProfile


class SimCard(SQLModel, table=True):
    """
    Modelo de tarjetas SIM asociadas a dispositivos.

    Un device normalmente tendrá solo una SIM activa.
    El ICCID es el identificador único de la tarjeta SIM.
    """

    __tablename__ = "sim_cards"
    __table_args__ = (
        Index("idx_sim_cards_device", "device_id"),
        Index("idx_sim_cards_iccid", "iccid"),
    )

    sim_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )

    device_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            Text,
            ForeignKey("devices.device_id", ondelete="CASCADE"),
            nullable=True,
            unique=True,  # Constraint: unique_active_sim_per_device
        ),
    )

    carrier: str = Field(
        default="KORE", sa_column=Column(Text, nullable=False, server_default="KORE")
    )

    iccid: str = Field(sa_column=Column(Text, nullable=False))

    imsi: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    msisdn: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    status: str = Field(
        default="active",
        sa_column=Column(Text, nullable=False, server_default="active"),
    )

    metadata_: Optional[dict] = Field(
        default=None, sa_column=Column("metadata", JSONB, nullable=True)
    )

    created_at: datetime = Field(
        sa_column=Column(
            TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
        )
    )

    updated_at: datetime = Field(
        sa_column=Column(
            TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
        )
    )

    # Relationships
    device: Optional["Device"] = Relationship(back_populates="sim_card")
    kore_profile: Optional["SimKoreProfile"] = Relationship(back_populates="sim_card")

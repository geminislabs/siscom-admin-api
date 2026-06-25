from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, SQLModel

from app.utils.datetime import utcnow

if TYPE_CHECKING:
    pass


class Command(SQLModel, table=True):
    """
    Modelo para comandos enviados a dispositivos.

    Estados del ciclo de vida:
    - pending: Comando creado, pendiente de envío
    - sent: Comando enviado al dispositivo
    - delivered: Comando entregado/confirmado por el dispositivo
    - failed: Comando falló en el envío o ejecución
    """

    __tablename__ = "commands"
    __table_args__ = (
        Index("idx_commands_device_id", "device_id"),
        Index("idx_commands_request_user_id", "request_user_id"),
        Index("idx_commands_status", "status"),
        Index("idx_commands_requested_at", "requested_at"),
        CheckConstraint(
            "status IN ('pending', 'sent', 'delivered', 'failed')",
            name="check_command_status",
        ),
    )

    command_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )

    # FK a command_templates se maneja a nivel de BD (no hay modelo SQLAlchemy)
    template_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(PGUUID(as_uuid=True), nullable=True),
    )

    command: str = Field(sa_column=Column(Text, nullable=False))
    media: str = Field(sa_column=Column(Text, nullable=False))

    request_user_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(PGUUID(as_uuid=True), nullable=True),
    )

    request_user_email: str = Field(sa_column=Column(Text, nullable=False))

    device_id: str = Field(
        sa_column=Column(
            Text,
            ForeignKey("devices.device_id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    requested_at: datetime = Field(
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

    status: str = Field(
        default="pending",
        sa_column=Column(Text, nullable=False, server_default="pending"),
    )

    command_metadata: Optional[dict[str, Any]] = Field(
        default=None,
        sa_column=Column("metadata", JSONB, nullable=True),
    )

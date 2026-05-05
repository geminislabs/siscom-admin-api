from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Index, SQLModel

from app.models.enums.gateway_event_status import GatewayEventStatus


class PaymentGatewayEvent(SQLModel, table=True):
    """
    Webhook recibido de cualquier pasarela.

    IDEMPOTENCIA: PK compuesta (gateway, external_event_id).
    Evento duplicado → INSERT conflict → ignorado.
    """

    __tablename__ = "payment_gateway_events"
    __table_args__ = (
        Index("idx_pge_gateway_type", "gateway", "event_type"),
        Index("idx_pge_processed", "processed_at"),
    )

    gateway: str = Field(sa_column=Column(Text, primary_key=True))
    external_event_id: str = Field(sa_column=Column(Text, primary_key=True))
    event_type: str = Field(sa_column=Column(Text, nullable=False))
    processed_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=sa_text("now()"),
        )
    )
    status: GatewayEventStatus = Field(
        default=GatewayEventStatus.PROCESSED,
        sa_column=Column(
            Text,
            nullable=False,
            server_default=GatewayEventStatus.PROCESSED.value,
        ),
    )
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    payload: Optional[dict] = Field(default=None, sa_column=Column(JSONB, nullable=True))

# app/models/payment_gateway_event.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Index, SQLModel

from app.core.pg_enums import gateway_event_status_pg, payment_gateway_pg
from app.models.enums.gateway_event_status import GatewayEventStatus


class PaymentGatewayEvent(SQLModel, table=True):
    """
    Webhook recibido de cualquier pasarela.
    PK compuesta (gateway, external_event_id) garantiza idempotencia.
    """

    __tablename__ = "payment_gateway_events"
    __table_args__ = (
        Index("idx_pge_type", "gateway", "event_type"),
        Index("idx_pge_processed", "processed_at"),
    )

    gateway: str = Field(sa_column=Column(payment_gateway_pg, primary_key=True))
    external_event_id: str = Field(sa_column=Column(Text, primary_key=True))
    event_type: str = Field(sa_column=Column(Text, nullable=False))

    event_status: GatewayEventStatus = Field(
        default=GatewayEventStatus.PROCESSED,
        sa_column=Column(
            gateway_event_status_pg,
            nullable=False,
            server_default=GatewayEventStatus.PROCESSED.value,
        ),
    )

    payload: Optional[dict] = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    error_message: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    retry_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=sa_text("0")),
    )
    processed_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=sa_text("now()"),
        )
    )

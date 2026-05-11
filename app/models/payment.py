# app/models/payment.py
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Numeric, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, SQLModel

from app.core.pg_enums import payment_gateway_pg, payment_method_type_pg, payment_status_pg


class PaymentStatus(str, enum.Enum):
    PENDING             = "PENDING"
    REQUIRES_ACTION     = "REQUIRES_ACTION"
    PROCESSING          = "PROCESSING"
    SUCCESS             = "SUCCESS"
    FAILED              = "FAILED"
    CANCELED            = "CANCELED"
    DISPUTED            = "DISPUTED"
    REFUNDED            = "REFUNDED"
    PARTIALLY_REFUNDED  = "PARTIALLY_REFUNDED"


class Payment(SQLModel, table=True):
    """
    Intento de pago.
    Pertenece a Invoice (y por transitividad a Account + Organization).
    """

    __tablename__ = "payments"
    __table_args__ = (
        Index("idx_pay_invoice",  "invoice_id"),
        Index("idx_pay_account",  "account_id"),
        Index("idx_pay_status",   "payment_status"),
        Index("idx_pay_method",   "payment_method_id"),
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa_text("gen_random_uuid()"),
        )
    )

    # ── Claves foráneas ──────────────────────────────────────────────────────
    invoice_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("invoices.id"),
            nullable=False,
        )
    )
    account_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("accounts.id"),
            nullable=False,
        )
    )
    organization_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("organizations.id"),
            nullable=False,
        )
    )

    # ── Pasarela ─────────────────────────────────────────────────────────────
    gateway: str = Field(sa_column=Column(payment_gateway_pg, nullable=False))
    gateway_payment_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    idempotency_key: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # ── Método de pago ────────────────────────────────────────────────────────
    payment_method_type: str = Field(
        sa_column=Column(payment_method_type_pg, nullable=False)
    )
    payment_method_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("payment_methods.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    payment_method_meta: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=sa_text("'{}'::jsonb")),
    )

    # ── Montos ────────────────────────────────────────────────────────────────
    amount: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    currency: str = Field(default="MXN", sa_column=Column(Text, nullable=False, server_default="MXN"))
    refunded_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(10, 2), nullable=False, server_default=sa_text("0")),
    )

    # ── MSI ───────────────────────────────────────────────────────────────────
    installments: Optional[int] = Field(default=None)
    installment_amount: Optional[Decimal] = Field(
        default=None, sa_column=Column(Numeric(10, 2), nullable=True)
    )

    # ── Estado ───────────────────────────────────────────────────────────────
    payment_status: str = Field(
        default=PaymentStatus.PENDING.value,
        sa_column=Column(
            payment_status_pg,
            nullable=False,
            server_default=PaymentStatus.PENDING.value,
        ),
    )

    # ── Ciclo de vida ─────────────────────────────────────────────────────────
    authorized_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    captured_at:   Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    initiated_at:  Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    succeeded_at:  Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    failed_at:     Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    canceled_at:   Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    refunded_at:   Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    # ── Fallo ─────────────────────────────────────────────────────────────────
    failure_code:    Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    failure_message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # ── Disputa ───────────────────────────────────────────────────────────────
    is_disputed: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=sa_text("false")),
    )
    dispute_id:          Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    dispute_reason:      Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    dispute_status:      Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    dispute_due_at:      Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    dispute_resolved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    # ── Antifraude ────────────────────────────────────────────────────────────
    risk_score:        Optional[int] = Field(default=None)
    risk_level:        Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    client_ip:         Optional[str] = Field(default=None, sa_column=Column(INET, nullable=True))
    device_session_id: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # ── Raw PSP ───────────────────────────────────────────────────────────────
    provider_response: Optional[dict] = Field(default=None, sa_column=Column(JSONB, nullable=True))

    # ── Pago manual ───────────────────────────────────────────────────────────
    registered_by: Optional[UUID] = Field(
        default=None,
        sa_column=Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True),
    )
    registration_notes: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # ── Metadata / Timestamps ─────────────────────────────────────────────────
    extra_data: dict = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default=sa_text("'{}'::jsonb")),
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=sa_text("now()"))
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=sa_text("now()"))
    )

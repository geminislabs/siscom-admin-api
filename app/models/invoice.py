# app/models/invoice.py
from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, SQLModel

from app.core.pg_enums import invoice_status_pg


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    VOID = "VOID"
    UNCOLLECTIBLE = "UNCOLLECTIBLE"


class Invoice(SQLModel, table=True):
    """
    Factura de suscripción.
    Los pagos (Payment) apuntan a esta tabla via invoice_id NOT NULL.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        Index("idx_inv_account", "account_id"),
        Index("idx_inv_org", "organization_id"),
        Index("idx_inv_sub", "subscription_id"),
        Index("idx_inv_status", "invoice_status"),
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa_text("gen_random_uuid()"),
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
    subscription_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("subscriptions.id"),
            nullable=True,
        ),
    )

    # ── Pasarela ──────────────────────────────────────────────────────────────
    # Puede ser NULL para facturas generadas internamente antes del pago
    gateway: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    external_invoice_id: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # ── Numeración ───────────────────────────────────────────────────────────
    invoice_number: str = Field(sa_column=Column(Text, nullable=False, unique=True))

    # ── Estado ───────────────────────────────────────────────────────────────
    invoice_status: str = Field(
        default=InvoiceStatus.DRAFT.value,
        sa_column=Column(
            invoice_status_pg,
            nullable=False,
            server_default=InvoiceStatus.DRAFT.value,
        ),
    )

    # ── Montos ────────────────────────────────────────────────────────────────
    subtotal: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    discount_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(10, 2), nullable=False, server_default=sa_text("0")),
    )
    tax_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(10, 2), nullable=False, server_default=sa_text("0")),
    )
    total_amount: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    currency: str = Field(
        default="MXN",
        sa_column=Column(Text, nullable=False, server_default="MXN"),
    )

    # ── Fechas ────────────────────────────────────────────────────────────────
    due_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    paid_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    voided_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # ── PDF / SAT (futuro) ────────────────────────────────────────────────────
    invoice_pdf_url: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    cfdi_uuid: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    extra_data: dict = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata", JSONB, nullable=False, server_default=sa_text("'{}'::jsonb")
        ),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=sa_text("now()")
        )
    )

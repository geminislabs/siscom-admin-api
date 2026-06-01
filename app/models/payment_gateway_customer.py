# app/models/payment_gateway_customer.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, SQLModel

from app.core.pg_enums import payment_gateway_pg


class PaymentGatewayCustomer(SQLModel, table=True):
    """
    Customer externo por (account_id, gateway).
    Stripe → cus_xxx
    Un account tiene como máximo un customer por pasarela.
    """

    __tablename__ = "payment_gateway_customers"
    __table_args__ = (
        UniqueConstraint("account_id", "gateway", name="pgc_account_gateway_key"),
        UniqueConstraint("gateway", "external_customer_id", name="pgc_external_key"),
        Index("idx_pgc_account", "account_id"),
        Index("idx_pgc_gateway", "gateway", "external_customer_id"),
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
            ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    gateway: str = Field(sa_column=Column(payment_gateway_pg, nullable=False))
    external_customer_id: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=sa_text("now()"))
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=sa_text("now()"))
    )
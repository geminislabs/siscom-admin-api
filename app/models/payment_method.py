# app/models/payment_method.py
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, SQLModel

from app.core.pg_enums import payment_gateway_pg, payment_method_type_pg
from app.models.enums.payment_method_type import PaymentMethodType


class PaymentMethod(SQLModel, table=True):
    """
    Referencia tokenizada de un instrumento de pago (vault).
    PCI DSS: solo almacenamos last4, brand, exp_month, exp_year.
    """

    __tablename__ = "payment_methods"
    __table_args__ = (
        UniqueConstraint("gateway", "external_token", name="pm_external_key"),
        Index("idx_pm_account", "account_id"),
        Index("idx_pm_gateway", "gateway", "external_token"),
        Index("idx_pm_account_gateway", "account_id", "gateway"),
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
    method_type: str = Field(
        default=PaymentMethodType.CARD.value,
        sa_column=Column(
            payment_method_type_pg,
            nullable=False,
            server_default=PaymentMethodType.CARD.value,
        ),
    )
    external_token: str = Field(sa_column=Column(Text, nullable=False))
    brand: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    last4: Optional[str] = Field(
        default=None, sa_column=Column(String(4), nullable=True)
    )
    exp_month: Optional[int] = Field(
        default=None, sa_column=Column(SmallInteger, nullable=True)
    )
    exp_year: Optional[int] = Field(
        default=None, sa_column=Column(SmallInteger, nullable=True)
    )
    fingerprint: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # Python attr = extra_data, DB column = metadata (compatibilidad con StripeGateway)
    extra_data: dict = Field(
        default_factory=dict,
        sa_column=Column(
            "metadata", JSONB, nullable=False, server_default=sa_text("'{}'::jsonb")
        ),
    )

    is_default: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=sa_text("false"))
    )
    is_active: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=sa_text("true"))
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

# app/core/pg_enums.py
"""
Tipos ENUM de PostgreSQL para usar en columnas SQLAlchemy.

create_type=False → el tipo ya existe en la BD (creado por el SQL directo).
                   SQLAlchemy solo lo referencia, no intenta crearlo.

USO:
    from app.core.pg_enums import payment_gateway_pg, payment_status_pg
    gateway = Column(payment_gateway_pg, nullable=False)
"""

from sqlalchemy.dialects.postgresql import ENUM as PgEnum

payment_gateway_pg = PgEnum(
    "stripe", "conekta", "mercadopago", "paypal", "manual",
    name="payment_gateway",
    create_type=False,
)

payment_method_type_pg = PgEnum(
    "card", "cash_voucher", "bank_transfer", "bank_redirect",
    "wallet", "installments", "real_time", "loyalty_points",
    "gift_card", "crypto", "manual",
    name="payment_method_type",
    create_type=False,
)

payment_status_pg = PgEnum(
    "PENDING", "REQUIRES_ACTION", "PROCESSING", "SUCCESS",
    "FAILED", "CANCELED", "DISPUTED", "REFUNDED", "PARTIALLY_REFUNDED",
    name="payment_status",
    create_type=False,
)

invoice_status_pg = PgEnum(
    "DRAFT", "OPEN", "PAID", "PAST_DUE", "VOID", "UNCOLLECTIBLE",
    name="invoice_status",
    create_type=False,
)

gateway_event_status_pg = PgEnum(
    "processed", "failed", "skipped",
    name="gateway_event_status",
    create_type=False,
)

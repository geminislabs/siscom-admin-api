# app/schemas/invoice.py
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.payment import PaymentStatus


class PaymentBrief(BaseModel):
    """Resumen del pago asociado a la factura."""
    id:                  UUID
    gateway:             str
    gateway_payment_id:  Optional[str]
    payment_status:      PaymentStatus
    payment_method_type: str
    amount:              Decimal
    currency:            str
    succeeded_at:        Optional[datetime]
    failed_at:           Optional[datetime]
    failure_code:        Optional[str]
    failure_message:     Optional[str]

    class Config:
        from_attributes = True


class InvoiceDetailOut(BaseModel):
    """
    Detalle completo de una factura.
    Incluye el pago asociado y, si es Stripe, la URL del recibo.
    """
    id:              UUID
    invoice_number:  str
    invoice_status:  str
    subtotal:        Decimal
    discount_amount: Decimal
    tax_amount:      Decimal
    total_amount:    Decimal
    currency:        str
    created_at:      datetime
    paid_at:         Optional[datetime]
    due_at:          Optional[datetime]
    subscription_id: Optional[UUID]
    invoice_pdf_url: Optional[str]

    # Pago asociado (puede ser None si aún no se intentó)
    payment: Optional[PaymentBrief]

    # URL del recibo en Stripe (fetched en tiempo real, None si falla o no aplica)
    stripe_receipt_url: Optional[str]

    class Config:
        from_attributes = True

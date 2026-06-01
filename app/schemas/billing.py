"""
Schemas para Billing (Read-Only).

Estos schemas representan información de facturación y pagos.
Son INFORMATIVOS y de solo lectura.

NOTA IMPORTANTE:
----------------
La integración con PSP (Stripe, etc.) NO está implementada.
Los endpoints de billing muestran información provisional basada en:
- Tabla payments (pagos registrados)
- Tabla subscriptions (para contexto de suscripciones)

Cuando se integre un PSP, estos schemas pueden extenderse
sin romper la API existente.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.payment import PaymentStatus


class InvoiceStatus(str, Enum):
    """Estados posibles de una factura/invoice."""
    DRAFT         = "DRAFT"
    OPEN          = "OPEN"
    PAID          = "PAID"
    PAST_DUE      = "PAST_DUE"
    VOID          = "VOID"
    UNCOLLECTIBLE = "UNCOLLECTIBLE"


class CurrentPlanInfo(BaseModel):
    """Información del plan actual."""
    plan_id:           UUID
    plan_name:         str
    plan_code:         str
    billing_cycle:     str
    next_billing_date: Optional[datetime] = None
    amount_due:        Decimal
    currency:          str = "MXN"

    class Config:
        from_attributes = True


class BillingStats(BaseModel):
    """Estadísticas de facturación."""
    total_paid:          Decimal
    payments_count:      int
    last_payment_date:   Optional[datetime] = None
    last_payment_amount: Optional[Decimal]  = None
    currency:            str = "MXN"

    class Config:
        from_attributes = True


class BillingSummaryOut(BaseModel):
    organization_id:          UUID
    organization_name:        str
    has_active_subscription:  bool
    current_plan:             Optional[CurrentPlanInfo] = None
    pending_amount:           Decimal = Decimal("0.00")
    stats:                    BillingStats
    billing_email:            Optional[str] = None

    class Config:
        from_attributes = True


class PaymentOut(BaseModel):
    id:           UUID
    amount:       Decimal
    currency:     str = "MXN"
    gateway:      Optional[str] = None
    payment_status: PaymentStatus
    succeeded_at: Optional[datetime] = None     # ← reemplaza paid_at
    created_at:   datetime

    class Config:
        from_attributes = True


class PaymentsListOut(BaseModel):
    payments: list[PaymentOut]
    total:    int
    has_more: bool


class InvoiceOut(BaseModel):
    id:             UUID
    invoice_number: str
    status:         InvoiceStatus
    amount:         Decimal
    currency:       str = "MXN"
    description:    str = "Suscripción NEXUS"
    created_at:     datetime
    paid_at:        Optional[datetime] = None
    due_date:       Optional[datetime] = None
    invoice_url:    Optional[str]      = None
    payment_id:     Optional[UUID]     = None
    subscription_id: Optional[UUID]   = None

    class Config:
        from_attributes = True


class InvoicesListOut(BaseModel):
    invoices: list[InvoiceOut]
    total:    int
    has_more: bool

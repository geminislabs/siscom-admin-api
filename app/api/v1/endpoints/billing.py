"""
Endpoints de Billing.

Expone información de facturación y pagos de forma estructurada.
"""
from decimal import Decimal
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization_id, get_current_user_full
from app.core.config import settings
from app.db.session import get_db
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organization import Organization
from app.models.payment import Payment, PaymentStatus
from app.models.plan import Plan
from app.models.user import User
from app.schemas.billing import (
    BillingStats,
    BillingSummaryOut,
    CurrentPlanInfo,
    InvoiceOut,
    InvoicesListOut,
    InvoiceStatus as SchemaInvoiceStatus,
    PaymentOut,
    PaymentsListOut,
)
from app.schemas.invoice import InvoiceDetailOut, PaymentBrief
from app.services.organization import OrganizationService
from app.services.subscription_query import get_primary_active_subscription

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_account_id(db: Session, organization_id: UUID) -> UUID | None:
    """
    Obtiene el account_id de una organización.
    Los pagos están ligados a la cuenta (account), no a la organización directamente.
    """
    org = db.query(Organization.account_id).filter(Organization.id == organization_id).first()
    return org.account_id if org else None


def _get_billing_stats(db: Session, organization_id: UUID) -> BillingStats:
    """
    Calcula estadísticas de facturación para una organización.
    """
    # Resolver account_id desde la organización
    account_id = _get_account_id(db, organization_id)

    if not account_id:
        return BillingStats(
            total_paid=Decimal(0), payments_count=0,
            last_payment_date=None, last_payment_amount=None, currency="MXN"
        )
    total_result = (
        db.query(func.sum(Payment.amount))
        .filter(Payment.account_id == account_id, Payment.payment_status == PaymentStatus.SUCCESS.value)
        .scalar()
    )
    payments_count = (
        db.query(Payment)
        .filter(Payment.account_id == account_id, Payment.payment_status == PaymentStatus.SUCCESS.value)
        .count()
    )
    last_payment = (
        db.query(Payment)
        .filter(Payment.account_id == account_id, Payment.payment_status == PaymentStatus.SUCCESS.value)
        .order_by(Payment.succeeded_at.desc())
        .first()
    )
    return BillingStats(
        total_paid=Decimal(total_result or 0),
        payments_count=payments_count,
        last_payment_date=last_payment.succeeded_at if last_payment else None,
        last_payment_amount=last_payment.amount if last_payment else None,
        currency="MXN",
    )


def _get_pending_amount(db: Session, organization_id: UUID) -> Decimal:
    """
    Calcula el monto pendiente de pago.
    """
    account_id = _get_account_id(db, organization_id)
    if not account_id:
        return Decimal(0)
    result = (
        db.query(func.sum(Payment.amount))
        .filter(Payment.account_id == account_id, Payment.payment_status == PaymentStatus.PENDING.value)
        .scalar()
    )
    return Decimal(result or 0)


def _fetch_stripe_receipt(gateway_payment_id: str) -> str | None:
    """
    Intenta obtener la URL del recibo de Stripe para un PaymentIntent.
    Retorna None si el PI no existe o la llamada falla (seed data, errores de red, etc.)
    """
    if not gateway_payment_id or gateway_payment_id.startswith("pi_seed"):
        return None  # seed data — no llamar a la API real de Stripe
    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        pi = stripe.PaymentIntent.retrieve(
            gateway_payment_id,
            expand=["latest_charge"],
        )
        charge = pi.get("latest_charge")
        if charge and isinstance(charge, dict):
            return charge.get("receipt_url")
        return None
    except Exception:
        return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=BillingSummaryOut)
def get_billing_summary(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
):
    """
    Obtiene el resumen de facturación de la organización.
    """
    organization = db.query(Organization).filter(Organization.id == organization_id).first()
    active_sub   = get_primary_active_subscription(db, organization_id)

    current_plan = None
    if active_sub:
        plan = db.query(Plan).filter(Plan.id == active_sub.plan_id).first()
        if plan:
            amount_due = plan.price_yearly if active_sub.billing_cycle == "YEARLY" else plan.price_monthly
            current_plan = CurrentPlanInfo(
                plan_id=plan.id, plan_name=plan.name, plan_code=plan.code,
                billing_cycle=active_sub.billing_cycle or "MONTHLY",
                next_billing_date=active_sub.expires_at,
                amount_due=amount_due, currency="MXN",
            )

    return BillingSummaryOut(
        organization_id=organization_id,
        organization_name=organization.name if organization else "Unknown",
        has_active_subscription=active_sub is not None,
        current_plan=current_plan,
        pending_amount=_get_pending_amount(db, organization_id),
        stats=_get_billing_stats(db, organization_id),
        billing_email=organization.billing_email if organization else None,
    )


@router.get("/payments", response_model=PaymentsListOut)
def list_payments(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, le=100, description="Máximo de resultados"),
    offset: int = Query(default=0, ge=0, description="Offset para paginación"),
    status: PaymentStatus | None = Query(default=None, description="Filtrar por estado"),
):
    """
    Lista el historial de pagos de la organización.
    """
    account_id = _get_account_id(db, organization_id)
    if not account_id:
        return PaymentsListOut(payments=[], total=0, has_more=False)

    query = db.query(Payment).filter(Payment.account_id == account_id)
    if status:
        query = query.filter(Payment.payment_status == status.value)

    total    = query.count()
    payments = query.order_by(Payment.succeeded_at.desc().nullslast()).limit(limit).offset(offset).all()

    return PaymentsListOut(
        payments=[PaymentOut.model_validate(p) for p in payments],
        total=total,
        has_more=(offset + len(payments)) < total,
    )


@router.get("/invoices", response_model=InvoicesListOut)
def list_invoices(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
):
    """
    Lista las facturas/invoices de la organización.

    NOTA: Provisional. Genera invoices a partir de pagos exitosos.
    Cuando se integre Stripe, vendrán de la API del PSP.
    """
    account_id = _get_account_id(db, organization_id)
    if not account_id:
        return InvoicesListOut(invoices=[], total=0, has_more=False)

    query       = db.query(Invoice).filter(Invoice.account_id == account_id)
    total       = query.count()
    invoices_db = query.order_by(Invoice.created_at.desc()).limit(limit).offset(offset).all()

    invoices = [
        InvoiceOut(
            id=inv.id,
            invoice_number=inv.invoice_number,
            status=SchemaInvoiceStatus(inv.invoice_status),
            amount=inv.total_amount,
            currency=inv.currency,
            description="Suscripción NEXUS",
            created_at=inv.created_at,
            paid_at=inv.paid_at,
            due_date=inv.due_at,
            invoice_url=inv.invoice_pdf_url,
            payment_id=None,
            subscription_id=inv.subscription_id,
        )
        for inv in invoices_db
    ]

    return InvoicesListOut(invoices=invoices, total=total, has_more=(offset + len(invoices)) < total)


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut)
def get_invoice_detail(
    invoice_id: UUID,
    organization_id: UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user_full),
    db: Session = Depends(get_db),
):
    """
    Detalle de una factura: datos de GeminisLabs + recibo de Stripe.

    Permisos: owner o billing.
    Devuelve el pago asociado y, si el gateway es Stripe y el PaymentIntent
    existe en Stripe, también la URL del recibo (stripe_receipt_url).
    Para datos de seed/test el campo stripe_receipt_url será null.
    """
    if not OrganizationService.can_manage_billing(db, current_user.id, organization_id):
        raise HTTPException(403, "Se requiere rol owner o billing")

    account_id = _get_account_id(db, organization_id)
    if not account_id:
        raise HTTPException(404, "Factura no encontrada")

    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.account_id == account_id)
        .first()
    )
    if not invoice:
        raise HTTPException(404, "Factura no encontrada")

    # ── Pago asociado ─────────────────────────────────────────────────────────
    # Toma el más reciente si hay varios (reintentos sobre misma factura)
    payment = (
        db.query(Payment)
        .filter(Payment.invoice_id == invoice_id)
        .order_by(Payment.created_at.desc())
        .first()
    )

    payment_brief: PaymentBrief | None = None
    stripe_receipt_url: str | None     = None

    if payment:
        payment_brief = PaymentBrief(
            id=payment.id,
            gateway=payment.gateway,
            gateway_payment_id=payment.gateway_payment_id,
            payment_status=PaymentStatus(payment.payment_status),
            payment_method_type=payment.payment_method_type,
            amount=payment.amount,
            currency=payment.currency,
            succeeded_at=payment.succeeded_at,
            failed_at=payment.failed_at,
            failure_code=payment.failure_code,
            failure_message=payment.failure_message,
        )

        # Intentar obtener el recibo de Stripe solo si el pago fue exitoso
        if payment.gateway == "stripe" and payment.payment_status == PaymentStatus.SUCCESS.value:
            stripe_receipt_url = _fetch_stripe_receipt(payment.gateway_payment_id)

    return InvoiceDetailOut(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        invoice_status=invoice.invoice_status,
        subtotal=invoice.subtotal,
        discount_amount=invoice.discount_amount,
        tax_amount=invoice.tax_amount,
        total_amount=invoice.total_amount,
        currency=invoice.currency,
        created_at=invoice.created_at,
        paid_at=invoice.paid_at,
        due_at=invoice.due_at,
        subscription_id=invoice.subscription_id,
        invoice_pdf_url=invoice.invoice_pdf_url,
        payment=payment_brief,
        stripe_receipt_url=stripe_receipt_url,
    )
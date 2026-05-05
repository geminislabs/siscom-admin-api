"""
Endpoints de Billing.

Expone información de facturación y pagos de forma estructurada.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization_id
from app.db.session import get_db
from app.models.organization import Organization
from app.models.payment import Payment, PaymentStatus
from app.models.plan import Plan
from app.schemas.billing import (
    BillingStats,
    BillingSummaryOut,
    CurrentPlanInfo,
    InvoiceOut,
    InvoicesListOut,
    InvoiceStatus,
    PaymentOut,
    PaymentsListOut,
)
from app.services.subscription_query import get_primary_active_subscription

router = APIRouter()


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
            total_paid=Decimal(0),
            payments_count=0,
            last_payment_date=None,
            last_payment_amount=None,
            currency="MXN",
        )

    # Total pagado (solo SUCCESS)
    total_result = (
        db.query(func.sum(Payment.amount))
        .filter(
            Payment.account_id == account_id,
            Payment.status == PaymentStatus.SUCCESS.value,
        )
        .scalar()
    )
    total_paid = Decimal(total_result or 0)

    # Conteo de pagos exitosos
    payments_count = (
        db.query(Payment)
        .filter(
            Payment.account_id == account_id,
            Payment.status == PaymentStatus.SUCCESS.value,
        )
        .count()
    )

    # Último pago
    last_payment = (
        db.query(Payment)
        .filter(
            Payment.account_id == account_id,
            Payment.status == PaymentStatus.SUCCESS.value,
        )
        .order_by(Payment.paid_at.desc())
        .first()
    )

    return BillingStats(
        total_paid=total_paid,
        payments_count=payments_count,
        last_payment_date=last_payment.paid_at if last_payment else None,
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

    pending_result = (
        db.query(func.sum(Payment.amount))
        .filter(
            Payment.account_id == account_id,
            Payment.status == PaymentStatus.PENDING.value,
        )
        .scalar()
    )
    return Decimal(pending_result or 0)


@router.get("/summary", response_model=BillingSummaryOut)
def get_billing_summary(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
):
    """
    Obtiene el resumen de facturación de la organización.
    """
    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )

    active_sub = get_primary_active_subscription(db, organization_id)

    current_plan = None
    if active_sub:
        plan = db.query(Plan).filter(Plan.id == active_sub.plan_id).first()
        if plan:
            amount_due = plan.price_monthly
            if active_sub.billing_cycle == "YEARLY":
                amount_due = plan.price_yearly

            current_plan = CurrentPlanInfo(
                plan_id=plan.id,
                plan_name=plan.name,
                plan_code=plan.code,
                billing_cycle=active_sub.billing_cycle or "MONTHLY",
                next_billing_date=active_sub.expires_at,
                amount_due=amount_due,
                currency="MXN",
            )

    stats = _get_billing_stats(db, organization_id)
    pending_amount = _get_pending_amount(db, organization_id)

    return BillingSummaryOut(
        organization_id=organization_id,
        organization_name=organization.name if organization else "Unknown",
        has_active_subscription=active_sub is not None,
        current_plan=current_plan,
        pending_amount=pending_amount,
        stats=stats,
        billing_email=organization.billing_email if organization else None,
    )


@router.get("/payments", response_model=PaymentsListOut)
def list_payments(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, le=100, description="Máximo de resultados"),
    offset: int = Query(default=0, ge=0, description="Offset para paginación"),
    status: PaymentStatus | None = Query(
        default=None, description="Filtrar por estado"
    ),
):
    """
    Lista el historial de pagos de la organización.
    """
    account_id = _get_account_id(db, organization_id)
    if not account_id:
        return PaymentsListOut(payments=[], total=0, has_more=False)

    query = db.query(Payment).filter(Payment.account_id == account_id)

    if status:
        query = query.filter(Payment.status == status.value)

    total = query.count()

    payments = (
        query.order_by(Payment.paid_at.desc()).limit(limit).offset(offset).all()
    )

    payments_out = [PaymentOut.model_validate(p) for p in payments]

    return PaymentsListOut(
        payments=payments_out, total=total, has_more=(offset + len(payments)) < total
    )


@router.get("/invoices", response_model=InvoicesListOut)
def list_invoices(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, le=100, description="Máximo de resultados"),
    offset: int = Query(default=0, ge=0, description="Offset para paginación"),
):
    """
    Lista las facturas/invoices de la organización.

    NOTA: Provisional. Genera invoices a partir de pagos exitosos.
    Cuando se integre Stripe, vendrán de la API del PSP.
    """
    account_id = _get_account_id(db, organization_id)
    if not account_id:
        return InvoicesListOut(invoices=[], total=0, has_more=False)

    query = db.query(Payment).filter(
        Payment.account_id == account_id,
        Payment.status == PaymentStatus.SUCCESS.value,
    )

    total = query.count()

    payments = query.order_by(Payment.paid_at.desc()).limit(limit).offset(offset).all()

    invoices = []
    for i, payment in enumerate(payments):
        invoice_date = payment.paid_at or payment.created_at
        year = invoice_date.year if invoice_date else datetime.utcnow().year
        seq = total - offset - i
        invoice_number = f"INV-{year}-{seq:04d}"

        invoice = InvoiceOut(
            id=payment.id,
            invoice_number=invoice_number,
            status=InvoiceStatus.PAID,
            amount=payment.amount,
            currency=payment.currency or "MXN",
            description="Suscripción NEXUS",
            created_at=payment.created_at,
            paid_at=payment.paid_at,
            due_date=None,
            invoice_url=payment.invoice_url,
            payment_id=payment.id,
            subscription_id=None,
        )
        invoices.append(invoice)

    return InvoicesListOut(
        invoices=invoices, total=total, has_more=(offset + len(invoices)) < total
    )

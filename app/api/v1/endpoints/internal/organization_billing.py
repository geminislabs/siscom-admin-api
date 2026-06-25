"""
Billing y suscripciones por organización — API interna GAC (solo lectura Stripe PM).
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_cognito_or_paseto
from app.api.v1.endpoints.billing import (
    _fetch_stripe_receipt,
    _get_account_id,
    _get_billing_stats,
    _get_pending_amount,
)
from app.db.session import get_db
from app.models.invoice import Invoice
from app.models.organization import Organization
from app.models.payment import Payment, PaymentStatus
from app.models.plan import Plan
from app.models.subscription import Subscription, SubscriptionStatus
from app.schemas.billing import (
    BillingSummaryOut,
    CurrentPlanInfo,
    InvoiceOut,
    InvoicesListOut,
    PaymentOut,
    PaymentsListOut,
)
from app.schemas.billing import InvoiceStatus as SchemaInvoiceStatus
from app.schemas.invoice import InvoiceDetailOut, PaymentBrief
from app.schemas.subscription import (
    SubscriptionCancelRequest,
    SubscriptionOut,
    SubscriptionsListOut,
    SubscriptionWithPlanOut,
)
from app.services.gateways import registry
from app.services.subscription_query import get_primary_active_subscription
from app.utils.datetime import utcnow

router = APIRouter()

get_auth_for_internal_org_billing = get_auth_cognito_or_paseto(
    required_service="gac",
    required_role="GAC_ADMIN",
)


def _organization_or_404(db: Session, organization_id: UUID) -> Organization:
    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )
    return organization


def _subscription_row_to_out(
    db: Session, sub: Subscription, now: datetime
) -> SubscriptionWithPlanOut:
    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
    is_active = sub.status in [
        SubscriptionStatus.ACTIVE.value,
        SubscriptionStatus.TRIAL.value,
    ] and (sub.expires_at is None or sub.expires_at > now)

    days_remaining = None
    if sub.expires_at:
        delta = sub.expires_at - now
        days_remaining = max(0, delta.days)

    return SubscriptionWithPlanOut(
        id=sub.id,
        organization_id=sub.organization_id,
        plan_id=sub.plan_id,
        status=sub.status,
        billing_cycle=sub.billing_cycle,
        started_at=sub.started_at,
        expires_at=sub.expires_at,
        cancelled_at=sub.cancelled_at,
        renewed_from=sub.renewed_from,
        auto_renew=sub.auto_renew,
        external_id=sub.external_id,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
        plan_name=plan.name if plan else None,
        plan_code=plan.code if plan else None,
        days_remaining=days_remaining,
        is_active=is_active,
    )


@router.get("/{organization_id}/subscriptions", response_model=SubscriptionsListOut)
def list_organization_subscriptions(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_org_billing),
    include_history: bool = Query(True, description="Incluir suscripciones históricas"),
    limit: int = Query(20, ge=1, le=100),
):
    _organization_or_404(db, organization_id)
    now = utcnow()

    query = db.query(Subscription).filter(
        Subscription.organization_id == organization_id
    )
    if not include_history:
        query = query.filter(
            Subscription.status.in_(
                [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIAL.value]
            )
        )

    subscriptions = query.order_by(Subscription.created_at.desc()).limit(limit).all()
    result = [_subscription_row_to_out(db, sub, now) for sub in subscriptions]
    active_count = sum(1 for row in result if row.is_active)

    return SubscriptionsListOut(
        subscriptions=result,
        active_count=active_count,
        total_count=len(result),
    )


@router.get(
    "/{organization_id}/subscriptions/{subscription_id}",
    response_model=SubscriptionWithPlanOut,
)
def get_organization_subscription(
    organization_id: UUID,
    subscription_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_org_billing),
):
    _organization_or_404(db, organization_id)
    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.id == subscription_id,
            Subscription.organization_id == organization_id,
        )
        .first()
    )
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suscripción no encontrada",
        )
    return _subscription_row_to_out(db, subscription, utcnow())


@router.post(
    "/{organization_id}/subscriptions/{subscription_id}/cancel",
    response_model=SubscriptionOut,
)
def cancel_organization_subscription(
    organization_id: UUID,
    subscription_id: UUID,
    request: SubscriptionCancelRequest,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_org_billing),
):
    _organization_or_404(db, organization_id)
    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.id == subscription_id,
            Subscription.organization_id == organization_id,
        )
        .first()
    )
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suscripción no encontrada",
        )
    if subscription.status == SubscriptionStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La suscripción ya está cancelada",
        )

    now = utcnow()
    subscription.cancelled_at = now
    subscription.auto_renew = False
    if request.cancel_immediately:
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.expires_at = now
    else:
        subscription.status = SubscriptionStatus.CANCELLED

    db.commit()
    db.refresh(subscription)
    return subscription


@router.get("/{organization_id}/billing/summary", response_model=BillingSummaryOut)
def get_organization_billing_summary(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_org_billing),
):
    organization = _organization_or_404(db, organization_id)
    active_sub = get_primary_active_subscription(db, organization_id)

    current_plan = None
    if active_sub:
        plan = db.query(Plan).filter(Plan.id == active_sub.plan_id).first()
        if plan:
            amount_due = (
                plan.price_yearly
                if active_sub.billing_cycle == "YEARLY"
                else plan.price_monthly
            )
            current_plan = CurrentPlanInfo(
                plan_id=plan.id,
                plan_name=plan.name,
                plan_code=plan.code,
                billing_cycle=active_sub.billing_cycle or "MONTHLY",
                next_billing_date=active_sub.expires_at,
                amount_due=amount_due,
                currency="MXN",
            )

    return BillingSummaryOut(
        organization_id=organization_id,
        organization_name=organization.name,
        has_active_subscription=active_sub is not None,
        current_plan=current_plan,
        pending_amount=_get_pending_amount(db, organization_id),
        stats=_get_billing_stats(db, organization_id),
        billing_email=organization.billing_email,
    )


@router.get("/{organization_id}/billing/payments", response_model=PaymentsListOut)
def list_organization_payments(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_org_billing),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    status: PaymentStatus | None = Query(default=None),
):
    _organization_or_404(db, organization_id)
    account_id = _get_account_id(db, organization_id)
    if not account_id:
        return PaymentsListOut(payments=[], total=0, has_more=False)

    query = db.query(Payment).filter(Payment.account_id == account_id)
    if status:
        query = query.filter(Payment.payment_status == status.value)

    total = query.count()
    payments = (
        query.order_by(Payment.succeeded_at.desc().nullslast())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return PaymentsListOut(
        payments=[PaymentOut.model_validate(p) for p in payments],
        total=total,
        has_more=(offset + len(payments)) < total,
    )


@router.get("/{organization_id}/billing/invoices", response_model=InvoicesListOut)
def list_organization_invoices(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_org_billing),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
):
    _organization_or_404(db, organization_id)
    account_id = _get_account_id(db, organization_id)
    if not account_id:
        return InvoicesListOut(invoices=[], total=0, has_more=False)

    query = db.query(Invoice).filter(Invoice.account_id == account_id)
    total = query.count()
    invoices_db = (
        query.order_by(Invoice.created_at.desc()).limit(limit).offset(offset).all()
    )

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
    return InvoicesListOut(
        invoices=invoices,
        total=total,
        has_more=(offset + len(invoices)) < total,
    )


@router.get(
    "/{organization_id}/billing/invoices/{invoice_id}",
    response_model=InvoiceDetailOut,
)
def get_organization_invoice_detail(
    organization_id: UUID,
    invoice_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_org_billing),
):
    _organization_or_404(db, organization_id)
    account_id = _get_account_id(db, organization_id)
    if not account_id:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.account_id == account_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    payment = (
        db.query(Payment)
        .filter(Payment.invoice_id == invoice_id)
        .order_by(Payment.created_at.desc())
        .first()
    )

    payment_brief: PaymentBrief | None = None
    stripe_receipt_url: str | None = None
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
        if (
            payment.gateway == "stripe"
            and payment.payment_status == PaymentStatus.SUCCESS.value
        ):
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


@router.get("/{organization_id}/billing/payment-methods")
def list_organization_payment_methods_readonly(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_org_billing),
    gateway: str = Query(default="stripe"),
):
    """Métodos de pago guardados (solo lectura; sin alta/baja desde GAC)."""
    _organization_or_404(db, organization_id)
    return registry.get(gateway.lower()).list_payment_methods(db, organization_id)

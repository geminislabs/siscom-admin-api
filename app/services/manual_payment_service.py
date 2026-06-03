"""Registro de pagos manuales (efectivo) desde GAC → activación de suscripción."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.account import Account
from app.models.enums.payment_gateway import PaymentGateway
from app.models.enums.payment_method_type import PaymentMethodType
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organization import Organization
from app.models.payment import Payment, PaymentStatus
from app.models.plan import Plan
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.schemas.manual_payment import ManualPaymentCreate, ManualPaymentResponse
from app.services import subscription_query

MIGRATE_MIN_UNITS = 20


def calculate_manual_payment_amount(
    plan: Plan, billing_cycle: str, active_units: int
) -> Decimal:
    cycle = billing_cycle.upper()
    if cycle == BillingCycle.YEARLY.value:
        unit_price = Decimal(str(plan.price_yearly))
    else:
        unit_price = Decimal(str(plan.price_monthly))
    return (unit_price * active_units).quantize(Decimal("0.01"))


def _validate_migrate_units(plan: Plan, active_units: int) -> None:
    if "migrate" in plan.code.lower() and active_units < MIGRATE_MIN_UNITS:
        raise HTTPException(
            status_code=400,
            detail=f"El plan {plan.code} requiere mínimo {MIGRATE_MIN_UNITS} unidades",
        )


def _activate_subscription(
    db: Session,
    organization_id: UUID,
    plan_id: UUID,
    billing_cycle: str,
    active_units: int,
) -> Subscription:
    now = datetime.now(timezone.utc)
    expires = now + (
        timedelta(days=365)
        if billing_cycle.upper() == BillingCycle.YEARLY.value
        else timedelta(days=30)
    )
    existing = subscription_query.get_primary_active_subscription(db, organization_id)
    if existing:
        existing.plan_id = plan_id
        existing.status = SubscriptionStatus.ACTIVE.value
        existing.expires_at = expires
        existing.billing_cycle = billing_cycle.upper()
        existing.active_units = active_units
        existing.current_period_start = now
        existing.current_period_end = expires
        existing.updated_at = now
        return existing

    sub = Subscription(
        plan_id=plan_id,
        organization_id=organization_id,
        status=SubscriptionStatus.ACTIVE.value,
        started_at=now,
        expires_at=expires,
        billing_cycle=billing_cycle.upper(),
        auto_renew=True,
        active_units=active_units,
        current_period_start=now,
        current_period_end=expires,
    )
    db.add(sub)
    db.flush()
    return sub


def _next_invoice_number(db: Session) -> str:
    """
    Numeración global INV-YYYY-NNNN (invoice_number es UNIQUE en toda la tabla).
    """
    year = datetime.now(timezone.utc).year
    prefix = f"INV-{year}-"
    rows = (
        db.query(Invoice.invoice_number)
        .filter(Invoice.invoice_number.like(f"{prefix}%"))
        .all()
    )
    max_seq = 0
    for (number,) in rows:
        try:
            max_seq = max(max_seq, int(str(number).removeprefix(prefix)))
        except ValueError:
            continue
    return f"{prefix}{max_seq + 1:04d}"


def register_manual_payment(
    db: Session,
    body: ManualPaymentCreate,
    *,
    gac_operator_id: Optional[str] = None,
) -> ManualPaymentResponse:
    if not settings.GAC_SYSTEM_USER_ID:
        raise HTTPException(
            status_code=500,
            detail="GAC_SYSTEM_USER_ID no configurado en el servidor",
        )

    try:
        registered_by = UUID(settings.GAC_SYSTEM_USER_ID)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="GAC_SYSTEM_USER_ID inválido",
        ) from exc

    account = db.query(Account).filter(Account.id == body.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account no encontrado")

    organization = (
        db.query(Organization)
        .filter(
            Organization.id == body.organization_id,
            Organization.account_id == body.account_id,
        )
        .first()
    )
    if not organization:
        raise HTTPException(
            status_code=404,
            detail="Organización no encontrada para este account",
        )

    plan = (
        db.query(Plan)
        .filter(Plan.id == body.plan_id, Plan.is_active.is_(True))
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Plan no encontrado o inactivo")

    _validate_migrate_units(plan, body.active_units)
    amount = calculate_manual_payment_amount(plan, body.billing_cycle, body.active_units)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="El monto calculado debe ser mayor a cero")

    now = datetime.now(timezone.utc)
    subscription = _activate_subscription(
        db,
        body.organization_id,
        body.plan_id,
        body.billing_cycle,
        body.active_units,
    )

    audit_lines = []
    if body.registration_notes:
        audit_lines.append(body.registration_notes.strip())
    if body.operator_email:
        audit_lines.append(f"Operador GAC: {body.operator_email}")
    if gac_operator_id:
        audit_lines.append(f"GAC user id: {gac_operator_id}")
    registration_notes = "\n".join(audit_lines) if audit_lines else None

    gateway_ref = body.transaction_ref or f"MANUAL-{uuid4()}"

    invoice = Invoice(
        account_id=body.account_id,
        organization_id=body.organization_id,
        subscription_id=subscription.id,
        gateway=PaymentGateway.MANUAL.value,
        invoice_number=_next_invoice_number(db),
        invoice_status=InvoiceStatus.PAID.value,
        subtotal=amount,
        discount_amount=Decimal("0"),
        tax_amount=Decimal("0"),
        total_amount=amount,
        currency="MXN",
        paid_at=now,
        extra_data={
            "manual": True,
            "billing_cycle": body.billing_cycle,
            "active_units": body.active_units,
            "plan_id": str(body.plan_id),
            "transaction_ref": body.transaction_ref,
        },
    )
    db.add(invoice)
    db.flush()

    payment = Payment(
        invoice_id=invoice.id,
        account_id=body.account_id,
        organization_id=body.organization_id,
        gateway=PaymentGateway.MANUAL.value,
        gateway_payment_id=gateway_ref,
        payment_method_type=PaymentMethodType.MANUAL.value,
        payment_method_meta={},
        amount=amount,
        currency="MXN",
        payment_status=PaymentStatus.SUCCESS.value,
        succeeded_at=now,
        registered_by=registered_by,
        registration_notes=registration_notes,
        extra_data={
            "gac_operator_id": gac_operator_id,
            "gac_operator_email": body.operator_email,
            "transaction_ref": body.transaction_ref,
        },
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    db.refresh(invoice)
    db.refresh(subscription)

    return ManualPaymentResponse(
        payment_id=payment.id,
        invoice_id=invoice.id,
        subscription_id=subscription.id,
        amount=str(amount),
        currency="MXN",
        billing_cycle=body.billing_cycle,
        active_units=body.active_units,
        plan_id=body.plan_id,
        organization_id=body.organization_id,
    )

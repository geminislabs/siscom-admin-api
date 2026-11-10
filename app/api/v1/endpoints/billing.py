"""
Endpoints de Billing.

Expone información de facturación y pagos de forma estructurada.
"""

from decimal import Decimal
from uuid import UUID

import stripe
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_organization_id_facturacion,
    get_current_user_full_facturacion,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organization import Organization
from app.models.payment import Payment, PaymentStatus
from app.models.payment_models import PaymentMethod
from app.models.plan import Plan
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.schemas.billing import (
    BillingStats,
    BillingSummaryOut,
    CurrentPlanInfo,
    InvoiceOut,
    InvoicesListOut,
    MoneyQuote,
    PaymentOut,
    PaymentsListOut,
    RenewalStateOut,
    StampCfdiIn,
    TaxProfileIn,
    TaxProfileOut,
)
from app.schemas.billing import (
    InvoiceStatus as SchemaInvoiceStatus,
)
from app.schemas.invoice import InvoiceDetailOut, PaymentBrief
from app.services import billing_period
from app.services.cfdi_service import (
    cfdi_filename,
    download_cfdi_file,
    get_tax_profile,
    stamp_cfdi,
    tax_profile_payload,
    upsert_tax_profile,
)
from app.services.gateways.stripe_gateway import RENEWAL_KEY_PREFIX
from app.services.organization import OrganizationService
from app.services.receipt_pdf import (
    invoice_allows_receipt,
    load_receipt_data,
    receipt_filename,
    render_receipt_pdf,
)
from app.services.subscription_query import get_primary_active_subscription

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_account_id(db: Session, organization_id: UUID) -> UUID | None:
    """
    Obtiene el account_id de una organización.
    Los pagos están ligados a la cuenta (account), no a la organización directamente.
    """
    org = (
        db.query(Organization.account_id)
        .filter(Organization.id == organization_id)
        .first()
    )
    return org.account_id if org else None


def _require_billing_account(
    db: Session, current_user: User, organization_id: UUID
) -> UUID:
    if not OrganizationService.can_manage_billing(db, current_user.id, organization_id):
        raise HTTPException(403, "Se requiere rol owner o billing")
    account_id = _get_account_id(db, organization_id)
    if not account_id:
        raise HTTPException(404, "Cuenta no encontrada")
    return account_id


def _get_account_invoice(db: Session, account_id: UUID, invoice_id: UUID) -> Invoice:
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.account_id == account_id)
        .first()
    )
    if not invoice:
        raise HTTPException(404, "Factura no encontrada")
    return invoice


def _invoice_out(inv: Invoice) -> InvoiceOut:
    stored_receipt = (inv.extra_data or {}).get("stripe_receipt_url")
    has_receipt = inv.invoice_status == InvoiceStatus.PAID.value or bool(inv.paid_at)
    return InvoiceOut(
        id=inv.id,
        invoice_number=inv.invoice_number,
        status=SchemaInvoiceStatus(inv.invoice_status),
        amount=inv.total_amount,
        currency=inv.currency,
        description="Suscripción NEXUS",
        created_at=inv.created_at,
        paid_at=inv.paid_at,
        due_date=inv.due_at,
        invoice_url=inv.invoice_pdf_url
        or (stored_receipt if isinstance(stored_receipt, str) else None),
        has_receipt=has_receipt,
        has_cfdi=bool(inv.cfdi_uuid),
        cfdi_uuid=inv.cfdi_uuid,
        payment_id=None,
        subscription_id=inv.subscription_id,
    )


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
    total_result = (
        db.query(func.sum(Payment.amount))
        .filter(
            Payment.account_id == account_id,
            Payment.payment_status == PaymentStatus.SUCCESS.value,
        )
        .scalar()
    )
    payments_count = (
        db.query(Payment)
        .filter(
            Payment.account_id == account_id,
            Payment.payment_status == PaymentStatus.SUCCESS.value,
        )
        .count()
    )
    last_payment = (
        db.query(Payment)
        .filter(
            Payment.account_id == account_id,
            Payment.payment_status == PaymentStatus.SUCCESS.value,
        )
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
        .filter(
            Payment.account_id == account_id,
            Payment.payment_status == PaymentStatus.PENDING.value,
        )
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


def _renewal_state(db: Session, sub: Subscription | None) -> RenewalStateOut | None:
    """
    Traduce el estado de dunning a un aviso accionable para el cliente.

    Se distingue el cargo que espera autorización del banco del que fue
    rechazado: en el primero el cliente tiene que hacer algo, en el segundo
    basta con actualizar la tarjeta.
    """
    if sub is None:
        return None

    state = RenewalStateOut(
        auto_renew=bool(sub.auto_renew),
        grace_until=sub.grace_until,
        attempts=sub.dunning_attempt_count or 0,
        next_attempt_at=sub.dunning_next_attempt,
    )
    if sub.status != SubscriptionStatus.PAST_DUE.value:
        return state

    pending_action = (
        db.query(Payment)
        .filter(
            Payment.organization_id == sub.organization_id,
            Payment.payment_status == PaymentStatus.REQUIRES_ACTION.value,
            # Solo renovaciones: un checkout interactivo a medias ya tiene su
            # propio aviso y pedir "autoriza el cargo" ahí confundiría.
            Payment.idempotency_key.startswith(RENEWAL_KEY_PREFIX),
        )
        .order_by(Payment.created_at.desc())
        .first()
    )
    if pending_action is not None:
        state.state = "action_required"
        state.message = (
            "Tu banco pide autorizar el cargo de la renovación. "
            "Confírmalo para no perder el servicio."
        )
        return state

    account_id = _get_account_id(db, sub.organization_id)
    has_card = account_id is not None and (
        db.query(PaymentMethod)
        .filter(
            PaymentMethod.account_id == account_id,
            PaymentMethod.is_active,
            PaymentMethod.is_default,
        )
        .first()
        is not None
    )
    if not has_card:
        state.state = "no_payment_method"
        state.message = (
            "No tenemos una tarjeta para renovar tu plan. Agrega un método de pago."
        )
        return state

    state.state = "past_due"
    state.message = sub.renewal_last_error or (
        "No pudimos cobrar la renovación. Revisa tu método de pago."
    )
    return state


@router.get("/summary", response_model=BillingSummaryOut)
def get_billing_summary(
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
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
            quoted = billing_period.quote_plan(
                plan, active_sub.billing_cycle or "MONTHLY"
            )
            current_plan = CurrentPlanInfo(
                plan_id=plan.id,
                plan_name=plan.name,
                plan_code=plan.code,
                billing_cycle=active_sub.billing_cycle or "MONTHLY",
                next_billing_date=active_sub.expires_at,
                amount_due=quoted["total"],
                currency="MXN",
                quote=MoneyQuote(
                    subtotal=quoted["subtotal"],
                    tax=quoted["tax"],
                    total=quoted["total"],
                    amount_cents=quoted["amount_cents"],
                ),
            )

    return BillingSummaryOut(
        organization_id=organization_id,
        organization_name=organization.name if organization else "Unknown",
        has_active_subscription=active_sub is not None,
        current_plan=current_plan,
        pending_amount=_get_pending_amount(db, organization_id),
        stats=_get_billing_stats(db, organization_id),
        billing_email=organization.billing_email if organization else None,
        renewal=_renewal_state(db, active_sub),
    )


@router.get("/payments", response_model=PaymentsListOut)
def list_payments(
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
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


@router.get("/invoices", response_model=InvoicesListOut)
def list_invoices(
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
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

    query = db.query(Invoice).filter(Invoice.account_id == account_id)
    total = query.count()
    invoices_db = (
        query.order_by(Invoice.created_at.desc()).limit(limit).offset(offset).all()
    )

    invoices = [_invoice_out(inv) for inv in invoices_db]

    return InvoicesListOut(
        invoices=invoices, total=total, has_more=(offset + len(invoices)) < total
    )


@router.get("/invoices/{invoice_id}/receipt.pdf")
def download_invoice_receipt(
    invoice_id: UUID,
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """PDF del comprobante de pago. No es un CFDI."""
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

    data, payment = load_receipt_data(db, invoice)
    if not invoice_allows_receipt(invoice, payment):
        raise HTTPException(
            409, "El comprobante estará disponible cuando el pago se acredite."
        )

    filename = receipt_filename(invoice.invoice_number)
    return Response(
        content=render_receipt_pdf(data),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/tax-profile", response_model=TaxProfileOut)
def get_account_tax_profile(
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """Datos fiscales SAT de la cuenta. Vacío (is_complete=false) si aún no hay perfil."""
    account_id = _require_billing_account(db, current_user, organization_id)
    profile = get_tax_profile(db, account_id)
    return TaxProfileOut.model_validate(tax_profile_payload(profile))


@router.put("/tax-profile", response_model=TaxProfileOut)
def put_account_tax_profile(
    payload: TaxProfileIn,
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """Guarda RFC/régimen y sincroniza el customer en Facturapi."""
    account_id = _require_billing_account(db, current_user, organization_id)
    profile = upsert_tax_profile(
        db,
        account_id,
        rfc=payload.rfc,
        legal_name=payload.legal_name,
        tax_system=payload.tax_system,
        zip_code=payload.zip,
        email=payload.email,
        default_cfdi_use=payload.default_cfdi_use,
    )
    return TaxProfileOut.model_validate(tax_profile_payload(profile))


@router.post("/invoices/{invoice_id}/cfdi", response_model=InvoiceOut)
def stamp_invoice_cfdi(
    invoice_id: UUID,
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
    payload: StampCfdiIn = Body(default=StampCfdiIn()),
):
    """Timbrar CFDI 4.0 (PUE). Idempotente: si ya hay UUID, lo devuelve."""
    account_id = _require_billing_account(db, current_user, organization_id)
    invoice = _get_account_invoice(db, account_id, invoice_id)
    stamped = stamp_cfdi(db, invoice, cfdi_use=payload.use)
    return _invoice_out(stamped)


def _cfdi_file_response(
    db: Session,
    current_user: User,
    organization_id: UUID,
    invoice_id: UUID,
    fmt: str,
) -> Response:
    account_id = _require_billing_account(db, current_user, organization_id)
    invoice = _get_account_invoice(db, account_id, invoice_id)
    content = download_cfdi_file(invoice, fmt)
    filename = cfdi_filename(invoice.invoice_number, fmt)
    media = "application/pdf" if fmt == "pdf" else "application/xml"
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/invoices/{invoice_id}/cfdi.pdf")
def download_invoice_cfdi_pdf(
    invoice_id: UUID,
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """PDF fiscal timbrado (proxy autenticado a Facturapi)."""
    return _cfdi_file_response(db, current_user, organization_id, invoice_id, "pdf")


@router.get("/invoices/{invoice_id}/cfdi.xml")
def download_invoice_cfdi_xml(
    invoice_id: UUID,
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """XML del SAT (proxy autenticado a Facturapi)."""
    return _cfdi_file_response(db, current_user, organization_id, invoice_id, "xml")


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut)
def get_invoice_detail(
    invoice_id: UUID,
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
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

        # Intentar obtener el recibo de Stripe solo si el pago fue exitoso
        if (
            payment.gateway == "stripe"
            and payment.payment_status == PaymentStatus.SUCCESS.value
        ):
            stripe_receipt_url = _fetch_stripe_receipt(payment.gateway_payment_id)
            if not stripe_receipt_url:
                stored = (invoice.extra_data or {}).get("stripe_receipt_url")
                if isinstance(stored, str) and stored.startswith("https://"):
                    stripe_receipt_url = stored

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
        has_cfdi=bool(invoice.cfdi_uuid),
        cfdi_uuid=invoice.cfdi_uuid,
        payment=payment_brief,
        stripe_receipt_url=stripe_receipt_url,
    )

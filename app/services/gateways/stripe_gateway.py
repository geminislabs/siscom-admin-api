# app/services/gateways/stripe_gateway.py
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import stripe
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session, object_session

from app.core.config import settings
from app.db.locks import advisory_xact_lock
from app.models.account import Account
from app.models.invoice import Invoice, InvoiceStatus
from app.models.organization import Organization
from app.models.payment import Payment, PaymentStatus
from app.models.payment_models import (
    GatewayEventStatus,
    PaymentGatewayCustomer,
    PaymentGatewayEvent,
    PaymentMethod,
    PaymentMethodType,
)
from app.models.plan import Plan
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.services import billing_period, money, subscription_query, suspension
from app.services.invoice_numbering import next_invoice_number

logger = logging.getLogger(__name__)

GATEWAY = "stripe"

_PI_CANCELED = "canceled"
_PI_PAID = "paid"
_PI_UNKNOWN = "unknown"

# Los pagos de renovación llevan prefijo para que el barrido de intentos
# abandonados del checkout interactivo no cancele un cobro automático en curso.
RENEWAL_KEY_PREFIX = "renew:"

RENEWAL_OK = "succeeded"
RENEWAL_ACTION_REQUIRED = "action_required"
RENEWAL_DECLINED = "declined"
RENEWAL_NO_CARD = "no_payment_method"
RENEWAL_UNAVAILABLE = "unavailable"


class StripeGateway:
    """Implementa GatewayProvider para Stripe. Instancia única (singleton)."""

    def __init__(self) -> None:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        stripe.max_network_retries = 3

    # ── Helpers internos ─────────────────────────────────────────────────────

    def _get_account(self, db: Session, organization_id: UUID) -> Account:
        """
        Navega Organization → Account.
        Los pagos pertenecen al Account (entidad comercial).
        Las suscripciones pertenecen a la Organization (entidad operativa).
        """
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        if not org:
            raise HTTPException(404, "Organización no encontrada")
        account = db.query(Account).filter(Account.id == org.account_id).first()
        if not account:
            raise HTTPException(
                400, "La organización no tiene cuenta comercial asociada"
            )
        return account

    def _assert_pm_ownership(
        self, db: Session, external_token: str, account_id: UUID
    ) -> PaymentMethod:
        """
        ANTI-IDOR: verifica que el PM pertenece al account antes de operar.
        Un usuario no puede eliminar/modificar tarjetas de otro account.
        """
        pm = (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.gateway == GATEWAY,
                PaymentMethod.external_token == external_token,
                PaymentMethod.account_id == account_id,
                PaymentMethod.is_active,
            )
            .first()
        )
        if not pm:
            raise HTTPException(404, "Método de pago no encontrado")
        return pm

    @staticmethod
    def _idem_key(*parts: str) -> str:
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:64]

    @staticmethod
    def _period_bucket(billing_cycle: str, when: datetime | None = None) -> str:
        when = when or datetime.now(timezone.utc)
        if billing_cycle.upper() == BillingCycle.YEARLY.value:
            return when.strftime("%Y")
        return when.strftime("%Y%m")

    def _idem_keys_for_period(
        self, account_id: UUID, plan_id: UUID, cycle: str
    ) -> list[str]:
        """Keys vigentes más keys YEARLY legacy (bucket YYYYMM anterior al hardening)."""
        now = datetime.now(timezone.utc)
        period = self._period_bucket(cycle, now)
        keys = [self._idem_key("pi", str(account_id), str(plan_id), cycle, period)]
        if cycle == BillingCycle.YEARLY.value:
            for month in range(1, 13):
                legacy = self._idem_key(
                    "pi",
                    str(account_id),
                    str(plan_id),
                    cycle,
                    f"{now.year}{month:02d}",
                )
                if legacy not in keys:
                    keys.append(legacy)
        return keys

    def _lock_existing_period_payment(
        self, db: Session, account_id: UUID, plan_id: UUID, cycle: str
    ) -> Payment | None:
        keys = self._idem_keys_for_period(account_id, plan_id, cycle)
        matches = (
            db.query(Payment)
            .filter(
                Payment.account_id == account_id,
                Payment.idempotency_key.in_(keys),
            )
            .with_for_update()
            .all()
        )
        if not matches:
            return None
        for payment in matches:
            if payment.payment_status == PaymentStatus.SUCCESS.value:
                return payment
        closed = {
            PaymentStatus.CANCELED.value,
            PaymentStatus.FAILED.value,
        }
        for payment in matches:
            if payment.payment_status not in closed:
                return payment
        return matches[0]

    @staticmethod
    def _advisory_xact_lock(db: Session, *parts: str) -> None:
        """Serializa operaciones de cobro por cuenta.

        Evita que dos checkouts simultáneos de la misma cuenta creen el primer
        pago a la vez — una fila que aún no existe, así que no hay
        `SELECT … FOR UPDATE` que la proteja.
        """
        advisory_xact_lock(db, *parts)

    @staticmethod
    def _already_processed() -> HTTPException:
        return HTTPException(
            409, "Este pago ya fue procesado exitosamente este período"
        )

    @staticmethod
    def _aware(ts: datetime | None) -> datetime | None:
        if ts is None:
            return None
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    @staticmethod
    def _webhook_payload_summary(event: dict) -> dict:
        obj = (event.get("data") or {}).get("object") or {}
        return {
            "id": event.get("id"),
            "type": event.get("type"),
            "created": event.get("created"),
            "livemode": event.get("livemode"),
            "object_id": obj.get("id"),
            "object_status": obj.get("status"),
            "amount": obj.get("amount"),
        }

    # ── Customer ─────────────────────────────────────────────────────────────

    def get_or_create_customer(
        self, db: Session, account_id: UUID, billing_email: str, account_name: str
    ) -> str:
        """
        Devuelve el stripe_customer_id del account.
        Lo crea en Stripe si no existe aún.
        """
        rec = (
            db.query(PaymentGatewayCustomer)
            .filter(
                PaymentGatewayCustomer.account_id == account_id,
                PaymentGatewayCustomer.gateway == GATEWAY,
            )
            .first()
        )
        if rec:
            return rec.external_customer_id

        try:
            customer = stripe.Customer.create(
                email=billing_email or "",
                name=account_name,
                metadata={"account_id": str(account_id)},
            )
        except stripe.error.StripeError as e:
            logger.error("Stripe Customer.create falló: %s", e.user_message)
            raise HTTPException(502, "Error al conectar con el procesador de pagos")

        rec = PaymentGatewayCustomer(
            account_id=account_id,
            gateway=GATEWAY,
            external_customer_id=customer.id,
        )
        db.add(rec)
        try:
            db.commit()
            db.refresh(rec)
        except IntegrityError:
            db.rollback()
            rec = (
                db.query(PaymentGatewayCustomer)
                .filter(
                    PaymentGatewayCustomer.account_id == account_id,
                    PaymentGatewayCustomer.gateway == GATEWAY,
                )
                .first()
            )
            if rec:
                return rec.external_customer_id
            raise HTTPException(502, "Error al registrar el cliente de pagos")
        logger.info(
            "Stripe Customer creado account=%s customer_id=%s", account_id, customer.id
        )
        return rec.external_customer_id

    # ── Setup Intent ──────────────────────────────────────────────────────────

    def create_setup_intent(self, db: Session, organization_id: UUID) -> dict:
        """
        Inicia el flujo de guardado de tarjeta.
        Devuelve client_token para que Stripe.js monte el Payment Element.
        Clave Stripe única por llamada: max_network_retries reutiliza esa key
        si el SDK reintenta la misma request. Un bucket horario reutilizaría
        un SetupIntent ya confirmado y bloquearía guardar una segunda tarjeta.
        """
        account = self._get_account(db, organization_id)
        customer_id = self.get_or_create_customer(
            db, account.id, account.billing_email or "", account.name
        )

        si_idem = self._idem_key("si", str(account.id), uuid4().hex)

        try:
            intent = stripe.SetupIntent.create(
                customer=customer_id,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
                usage="off_session",
                metadata={"account_id": str(account.id)},
                idempotency_key=si_idem,
            )
        except stripe.error.StripeError as e:
            logger.error("SetupIntent.create falló: %s", e.user_message)
            raise HTTPException(502, "Error al inicializar el guardado de tarjeta")

        return {"client_token": intent.client_secret, "gateway": GATEWAY}

    def confirm_setup_intent(
        self, db: Session, organization_id: UUID, setup_intent_id: str
    ) -> list[dict]:
        """
        Copia a BD una tarjeta que Stripe.js ya confirmó.

        El webhook `setup_intent.succeeded` hace lo mismo y es idempotente.
        En local no hay `stripe listen`, y el front no puede esperar un evento
        que nunca llega: si el SetupIntent está succeeded y es de esta cuenta,
        se persiste aquí.
        """
        account = self._get_account(db, organization_id)
        sid = (setup_intent_id or "").strip()
        if (
            not sid.startswith("seti_")
            or len(sid) > 255
            or any(c.isspace() for c in sid)
        ):
            raise HTTPException(400, "setup_intent inválido")

        try:
            intent = stripe.SetupIntent.retrieve(sid)
        except stripe.error.InvalidRequestError:
            raise HTTPException(404, "No encontramos ese guardado de tarjeta")
        except stripe.error.StripeError as e:
            logger.error("SetupIntent.retrieve falló: %s", e.user_message)
            raise HTTPException(502, "No se pudo verificar el guardado de la tarjeta")

        if getattr(intent, "status", None) != "succeeded":
            raise HTTPException(
                409,
                "El banco aún no confirmó la tarjeta. Intenta de nuevo en un momento.",
            )

        customer_id = getattr(intent, "customer", None)
        cust = (
            db.query(PaymentGatewayCustomer)
            .filter(
                PaymentGatewayCustomer.gateway == GATEWAY,
                PaymentGatewayCustomer.external_customer_id == customer_id,
                PaymentGatewayCustomer.account_id == account.id,
            )
            .first()
        )
        if not cust:
            raise HTTPException(403, "Este guardado no pertenece a tu cuenta")

        intent_dict = (
            intent.to_dict()
            if hasattr(intent, "to_dict")
            else {
                "payment_method": getattr(intent, "payment_method", None),
                "customer": customer_id,
            }
        )
        pm = self._persist_setup_payment_method(db, intent_dict)
        if pm is None:
            raise HTTPException(
                502,
                "Stripe confirmó la tarjeta pero no pudimos registrarla. Intenta de nuevo.",
            )
        db.commit()
        return self.list_payment_methods(db, organization_id)

    # ── Payment Intent ────────────────────────────────────────────────────────

    def create_payment_intent(
        self, db: Session, organization_id: UUID, plan_id: UUID, billing_cycle: str
    ) -> dict:
        """
        Crea un PaymentIntent para el pago de una suscripción.

        SEGURIDAD: El monto proviene de la tabla plans en la BD.
        El frontend envía plan_id + billing_cycle, NUNCA el monto.

        IDEMPOTENCIA: sha256(account + plan + ciclo + bucket).
        MONTHLY → YYYYMM. YEARLY → YYYY (un cobro por año calendario).

        MONTO: precio del plan + IVA. Se cobra el mismo total que la factura
        desglosa, para que el cargo coincida con lo que el cliente aprobó.
        """
        account = self._get_account(db, organization_id)
        customer_id = self.get_or_create_customer(
            db, account.id, account.billing_email or "", account.name
        )

        plan = db.query(Plan).filter(Plan.id == plan_id, Plan.is_active).first()
        if not plan:
            raise HTTPException(404, "Plan no encontrado o inactivo")

        cycle = billing_cycle.upper()
        list_price = (
            plan.price_yearly
            if cycle == BillingCycle.YEARLY.value
            else plan.price_monthly
        )
        subtotal, tax_mxn, total_mxn = billing_period.with_iva(list_price or 0)
        amount_cents = billing_period.to_cents(total_mxn)
        if subtotal <= 0:
            raise HTTPException(400, "El plan no tiene precio configurado")

        self._advisory_xact_lock(db, "pi", str(account.id))

        period_keys = self._idem_keys_for_period(account.id, plan_id, cycle)
        idem = period_keys[0]

        stripe_pi_idempotency_key = idem
        payment_row_to_refresh: Payment | None = None

        existing = self._lock_existing_period_payment(db, account.id, plan_id, cycle)
        if existing:
            if existing.payment_status == PaymentStatus.SUCCESS.value:
                raise self._already_processed()
            if existing.gateway_payment_id:
                try:
                    prior_pi = stripe.PaymentIntent.retrieve(
                        existing.gateway_payment_id
                    )
                    if prior_pi.status == "succeeded":
                        self._fulfill_local_success(
                            db, existing, self._pi_as_dict(prior_pi)
                        )
                        db.commit()
                        raise self._already_processed()
                    if prior_pi.status != "canceled":
                        prior_amount = int(getattr(prior_pi, "amount", 0) or 0)
                        if prior_amount == amount_cents:
                            return self._pi_response(db, prior_pi, existing, plan)
                        logger.info(
                            "PI %s cotizado en %s centavos y el vigente es %s; se reemite",
                            existing.gateway_payment_id,
                            prior_amount,
                            amount_cents,
                        )
                        outcome = self._settle_obsolete_pi(db, existing)
                        if outcome == _PI_PAID:
                            db.commit()
                            raise self._already_processed()
                        if outcome == _PI_UNKNOWN:
                            # 5xx a propósito: el resultado es desconocido, así
                            # que la reserva de idempotencia se abandona y el
                            # reintento puede volver a cotizar.
                            raise HTTPException(
                                503,
                                "No pudimos verificar tu intento anterior con el "
                                "procesador de pagos. Espera un momento y vuelve "
                                "a intentarlo.",
                            )
                    stripe_pi_idempotency_key = self._idem_key(
                        idem, "stripe_reissue", existing.gateway_payment_id
                    )
                    payment_row_to_refresh = existing
                except HTTPException:
                    raise
                except stripe.error.StripeError as ex:
                    logger.warning(
                        "No se pudo consultar PI %s; reemitiendo con clave Stripe distinta: %s",
                        existing.gateway_payment_id,
                        ex,
                    )
                    stripe_pi_idempotency_key = self._idem_key(
                        idem, "stripe_reissue_err", existing.gateway_payment_id or ""
                    )
                    payment_row_to_refresh = existing

        stale = (
            db.query(Payment)
            .filter(
                Payment.account_id == account.id,
                Payment.payment_status == PaymentStatus.PENDING.value,
                Payment.idempotency_key.notin_(period_keys),
                # Un cobro de renovación no es un checkout abandonado: cancelarlo
                # desde otra pestaña dejaría la suscripción sin cobrar.
                ~Payment.idempotency_key.startswith(RENEWAL_KEY_PREFIX),
            )
            .all()
        )
        touched_stale = False
        for p in stale:
            if p.gateway_payment_id and self._settle_obsolete_pi(db, p) != _PI_CANCELED:
                continue
            p.payment_status = PaymentStatus.CANCELED.value
            p.canceled_at = datetime.now(timezone.utc)
            if p.invoice_id:
                inv = db.query(Invoice).filter(Invoice.id == p.invoice_id).first()
                if inv and inv.invoice_status != InvoiceStatus.PAID.value:
                    inv.invoice_status = InvoiceStatus.VOID.value
            touched_stale = True
        if touched_stale:
            db.flush()

        try:
            pi_params: dict = {
                "amount": amount_cents,
                "currency": "mxn",
                "customer": customer_id,
                "confirm": False,
                "automatic_payment_methods": {
                    "enabled": True,
                    "allow_redirects": "never",
                },
                "setup_future_usage": "off_session",
                "metadata": {
                    "account_id": str(account.id),
                    "organization_id": str(organization_id),
                    "plan_id": str(plan_id),
                    "plan_code": plan.code or "",
                    "billing_cycle": cycle,
                },
            }
            pi = stripe.PaymentIntent.create(
                **pi_params, idempotency_key=stripe_pi_idempotency_key
            )
        except stripe.error.StripeError as e:
            logger.error("PaymentIntent.create falló: %s", e.user_message)
            raise HTTPException(502, "Error al inicializar el pago")

        conflict_db = (
            db.query(Payment).filter(Payment.gateway_payment_id == pi.id).first()
        )
        if conflict_db is not None and conflict_db is not payment_row_to_refresh:
            if conflict_db.account_id != account.id:
                logger.error(
                    "gateway_payment_id %s repetido entre cuentas (conflicto Stripe/BD)",
                    pi.id,
                )
                raise HTTPException(
                    409,
                    "Conflicto al registrar el pago. Refresca e intenta de nuevo o contacta soporte.",
                )
            if conflict_db.payment_status == PaymentStatus.SUCCESS.value:
                raise self._already_processed()
            if conflict_db.idempotency_key != idem:
                conflict_db.idempotency_key = idem
            db.commit()
            db.refresh(conflict_db)
            return self._pi_response(db, pi, conflict_db, plan)

        invoice = Invoice(
            account_id=account.id,
            organization_id=organization_id,
            invoice_number=next_invoice_number(db),
            invoice_status=InvoiceStatus.OPEN.value,
            subtotal=subtotal,
            discount_amount=Decimal("0"),
            tax_amount=tax_mxn,
            total_amount=total_mxn,
            currency="MXN",
        )
        db.add(invoice)

        payment_extra = {"plan_id": str(plan_id), "billing_cycle": cycle}

        payment: Payment
        try:
            if payment_row_to_refresh:
                payment = payment_row_to_refresh
                if payment.invoice_id:
                    prev_inv = (
                        db.query(Invoice)
                        .filter(Invoice.id == payment.invoice_id)
                        .first()
                    )
                    if prev_inv:
                        prev_inv.invoice_status = InvoiceStatus.VOID.value
                db.flush()
                payment.invoice_id = invoice.id
                payment.gateway_payment_id = pi.id
                payment.idempotency_key = idem
                payment.amount = total_mxn
                payment.payment_status = PaymentStatus.PENDING.value
                payment.refunded_amount = Decimal("0")
                payment.extra_data = {**(payment.extra_data or {}), **payment_extra}
            else:
                db.flush()
                payment = Payment(
                    invoice_id=invoice.id,
                    account_id=account.id,
                    organization_id=organization_id,
                    gateway=GATEWAY,
                    gateway_payment_id=pi.id,
                    idempotency_key=idem,
                    payment_method_type=PaymentMethodType.CARD.value,
                    payment_method_id=None,
                    payment_method_meta={},
                    amount=total_mxn,
                    currency="MXN",
                    refunded_amount=Decimal("0"),
                    payment_status=PaymentStatus.PENDING.value,
                    extra_data=payment_extra,
                )
                db.add(payment)
            db.commit()
            db.refresh(payment)
        except IntegrityError as exc:
            db.rollback()
            orig_txt = str(exc.orig) if exc.orig else ""
            if (
                "idx_pay_gateway_id" not in orig_txt
                and "gateway_payment_id" not in orig_txt
            ):
                raise HTTPException(
                    500,
                    "No se pudo registrar el intento de pago. Intenta en un momento.",
                ) from exc
            reused = (
                db.query(Payment).filter(Payment.gateway_payment_id == pi.id).first()
            )
            if (
                reused
                and reused.account_id == account.id
                and reused.payment_status != PaymentStatus.SUCCESS.value
            ):
                if reused.idempotency_key != idem:
                    reused.idempotency_key = idem
                db.commit()
                db.refresh(reused)
                return self._pi_response(db, pi, reused, plan)
            raise HTTPException(
                409,
                "Este intento ya está registrado. Recarga la página y vuelve a intentarlo.",
            ) from exc

        return self._pi_response(db, pi, payment, plan)

    def _settle_obsolete_pi(self, db: Session, payment: Payment) -> str:
        """
        Da de baja en Stripe un PaymentIntent que ya no sirve.

        Devuelve _PI_CANCELED si quedó cancelado y la fila puede marcarse
        CANCELED; _PI_PAID si en realidad ya estaba cobrado (el pago se cumple
        aquí mismo); _PI_UNKNOWN si Stripe no respondió. Un cobro que pudo haber
        sido exitoso nunca se marca como cancelado.
        """
        pi_id = payment.gateway_payment_id
        try:
            stripe.PaymentIntent.cancel(pi_id)
            return _PI_CANCELED
        except stripe.error.InvalidRequestError:
            pass
        except stripe.error.StripeError as exc:
            logger.warning(
                "No se pudo cancelar PI %s; se deja PENDING hasta confirmar: %s",
                pi_id,
                exc,
            )
            return _PI_UNKNOWN

        try:
            prior_pi = stripe.PaymentIntent.retrieve(pi_id)
        except stripe.error.StripeError as exc:
            logger.warning(
                "PI %s no cancelable y no consultable; se deja PENDING: %s", pi_id, exc
            )
            return _PI_UNKNOWN

        if prior_pi.status == "succeeded":
            logger.warning(
                "PI %s ya estaba cobrado al dar de baja el checkout; se cumple el pago",
                pi_id,
            )
            self._fulfill_local_success(db, payment, self._pi_as_dict(prior_pi))
            return _PI_PAID

        return _PI_CANCELED

    def _pi_response(
        self, db: Session, pi: stripe.PaymentIntent, payment: Payment, plan: Plan
    ) -> dict:
        """
        El desglose sale de la factura del intento, no del precio de lista: así
        el cliente ve exactamente el importe que Stripe va a cargar.
        """
        total = money.parse(payment.amount or 0)
        invoice = (
            db.query(Invoice).filter(Invoice.id == payment.invoice_id).first()
            if payment.invoice_id
            else None
        )
        if invoice is not None:
            subtotal = money.parse(invoice.subtotal or 0)
            tax = money.parse(invoice.tax_amount or 0)
        else:
            subtotal, tax = total, money.parse(0)
        return {
            "client_token": pi.client_secret,
            "gateway": GATEWAY,
            "payment_id": str(payment.id),
            # String + centavos: JSON no tiene Decimal y float no puede
            # representar centavos. El cliente muestra esto, no lo calcula.
            "amount_mxn": money.dump(subtotal),
            "tax_mxn": money.dump(tax),
            "amount_with_iva": money.dump(total),
            "amount_cents": money.to_cents(total),
            "currency": payment.currency or "MXN",
            "plan_name": plan.name,
            "plan_code": plan.code,
            "invoice_id": str(payment.invoice_id) if payment.invoice_id else None,
            "invoice_number": invoice.invoice_number if invoice is not None else None,
        }

    # ── Renovación automática ─────────────────────────────────────────────────

    @staticmethod
    def _renewal_bucket(subscription: Subscription) -> str:
        """
        Identifica el período que se está renovando por su fecha de vencimiento.
        Se mantiene estable entre reintentos y cambia al renovarse, así que sirve
        de llave natural para no cobrar dos veces el mismo período.
        """
        end = billing_period.as_aware(subscription.expires_at)
        return end.strftime("%Y%m%d") if end else "sin-vigencia"

    def default_payment_method(
        self, db: Session, account_id: UUID
    ) -> PaymentMethod | None:
        return (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.account_id == account_id,
                PaymentMethod.gateway == GATEWAY,
                PaymentMethod.is_active,
                PaymentMethod.is_default,
            )
            .first()
        )

    def charge_renewal(
        self, db: Session, subscription: Subscription, attempt: int
    ) -> dict:
        """
        Cobra la renovación con la tarjeta guardada, sin el cliente presente.

        La llave de BD es estable por período renovado, así que dos corridas del
        cron no generan dos cargos. La llave de Stripe incluye el número de
        intento: sin eso, Stripe devolvería el rechazo cacheado del intento
        anterior y ningún reintento podría cobrar nunca.
        """
        plan = (
            db.query(Plan)
            .filter(Plan.id == subscription.plan_id, Plan.is_active)
            .first()
        )
        if plan is None:
            return {
                "status": RENEWAL_UNAVAILABLE,
                "error": "El plan de la suscripción ya no está disponible",
            }

        cycle = (subscription.billing_cycle or BillingCycle.MONTHLY.value).upper()
        list_price = (
            plan.price_yearly
            if cycle == BillingCycle.YEARLY.value
            else plan.price_monthly
        )
        subtotal, tax_mxn, total_mxn = billing_period.with_iva(list_price or 0)
        if subtotal <= 0:
            return {
                "status": RENEWAL_UNAVAILABLE,
                "error": "El plan no tiene precio configurado",
            }
        amount_cents = billing_period.to_cents(total_mxn)

        try:
            account = self._get_account(db, subscription.organization_id)
        except HTTPException as exc:
            return {"status": RENEWAL_UNAVAILABLE, "error": exc.detail}

        pm = self.default_payment_method(db, account.id)
        if pm is None:
            return {
                "status": RENEWAL_NO_CARD,
                "error": "No hay una tarjeta guardada para cobrar la renovación",
            }

        try:
            customer_id = self.get_or_create_customer(
                db, account.id, account.billing_email or "", account.name
            )
        except HTTPException as exc:
            return {"status": RENEWAL_UNAVAILABLE, "error": exc.detail}

        db_key = RENEWAL_KEY_PREFIX + self._idem_key(
            "renew", str(subscription.id), self._renewal_bucket(subscription)
        )
        payment = (
            db.query(Payment)
            .filter(Payment.idempotency_key == db_key)
            .with_for_update()
            .first()
        )
        if (
            payment is not None
            and payment.payment_status == PaymentStatus.SUCCESS.value
        ):
            return {"status": RENEWAL_OK, "payment_id": str(payment.id)}

        if payment is not None and payment.gateway_payment_id:
            verdict = self._renewal_prior_intent(db, payment)
            if verdict is not None:
                return verdict

        invoice = self._renewal_invoice(
            db, account.id, subscription, payment, subtotal, tax_mxn, total_mxn
        )
        payment = self._renewal_payment(
            db, account.id, subscription, payment, invoice, db_key, total_mxn, pm, plan
        )

        try:
            pi = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency="mxn",
                customer=customer_id,
                payment_method=pm.external_token,
                off_session=True,
                confirm=True,
                metadata={
                    "account_id": str(account.id),
                    "organization_id": str(subscription.organization_id),
                    "plan_id": str(subscription.plan_id),
                    "plan_code": plan.code or "",
                    "billing_cycle": cycle,
                    "renewal": "true",
                    "subscription_id": str(subscription.id),
                },
                idempotency_key=self._idem_key(db_key, "attempt", str(attempt)),
            )
        except stripe.error.CardError as exc:
            return self._renewal_card_error(db, payment, exc)
        except stripe.error.StripeError as exc:
            logger.error("Cobro de renovación no pudo emitirse: %s", exc)
            payment.provider_response = {"error": str(exc)}
            payment.updated_at = datetime.now(timezone.utc)
            db.flush()
            return {
                "status": RENEWAL_UNAVAILABLE,
                "error": "No pudimos comunicarnos con el procesador de pagos",
                "payment_id": str(payment.id),
            }

        payment.gateway_payment_id = pi.id
        if pi.status in ("succeeded", "requires_capture"):
            self._fulfill_local_success(db, payment, self._pi_as_dict(pi))
            db.flush()
            return {"status": RENEWAL_OK, "payment_id": str(payment.id)}

        if pi.status in ("requires_action", "requires_confirmation"):
            payment.payment_status = PaymentStatus.REQUIRES_ACTION.value
            db.flush()
            return {
                "status": RENEWAL_ACTION_REQUIRED,
                "error": "Tu banco pide autorizar el cargo",
                "payment_id": str(payment.id),
            }

        # processing y demás estados intermedios: el webhook cierra el pago.
        payment.payment_status = PaymentStatus.PROCESSING.value
        db.flush()
        return {"status": RENEWAL_OK, "payment_id": str(payment.id), "pending": True}

    def _renewal_prior_intent(self, db: Session, payment: Payment) -> dict | None:
        """
        Revisa el intento del reintento anterior antes de emitir uno nuevo.

        Devuelve None si se puede volver a cobrar. Si el cliente autorizó el
        cargo justo antes de esta corrida, o si sigue pendiente de autorizar,
        emitir un segundo PaymentIntent lo cobraría dos veces.
        """
        pi_id = payment.gateway_payment_id
        try:
            prior = stripe.PaymentIntent.retrieve(pi_id)
        except stripe.error.StripeError as exc:
            logger.warning(
                "No se pudo consultar el intento previo %s; no se reintenta esta "
                "corrida para no cobrar dos veces: %s",
                pi_id,
                exc,
            )
            return {
                "status": RENEWAL_UNAVAILABLE,
                "error": "No pudimos verificar el intento anterior",
                "payment_id": str(payment.id),
            }

        if prior.status in ("succeeded", "requires_capture"):
            self._fulfill_local_success(db, payment, self._pi_as_dict(prior))
            db.flush()
            logger.info(
                "El intento previo %s ya estaba cobrado; se cumple el pago", pi_id
            )
            return {"status": RENEWAL_OK, "payment_id": str(payment.id)}

        if prior.status in ("requires_action", "requires_confirmation", "processing"):
            logger.info(
                "El intento previo %s sigue abierto (%s); se espera al cliente",
                pi_id,
                prior.status,
            )
            return {
                "status": RENEWAL_ACTION_REQUIRED,
                "error": "Tu banco pide autorizar el cargo",
                "payment_id": str(payment.id),
            }

        return None

    def _renewal_card_error(
        self, db: Session, payment: Payment, exc: stripe.error.CardError
    ) -> dict:
        """
        Un rechazo con `authentication_required` no es un rechazo definitivo: el
        banco pide 3DS, que un cobro sin el cliente presente no puede resolver.
        Se distingue para pedirle al cliente que lo autorice en el panel.
        """
        err = getattr(exc, "error", None)
        code = getattr(err, "code", None) or getattr(exc, "code", None) or ""
        pi = getattr(err, "payment_intent", None) or {}
        pi_id = pi.get("id") if isinstance(pi, dict) else getattr(pi, "id", None)
        message = getattr(exc, "user_message", None) or str(exc)

        now = datetime.now(timezone.utc)
        if pi_id:
            payment.gateway_payment_id = pi_id
        payment.provider_response = {"error": message, "code": code}
        payment.updated_at = now

        if code == "authentication_required":
            payment.payment_status = PaymentStatus.REQUIRES_ACTION.value
            db.flush()
            logger.info("Renovación requiere 3DS pago=%s", payment.id)
            return {
                "status": RENEWAL_ACTION_REQUIRED,
                "error": "Tu banco pide autorizar el cargo",
                "payment_id": str(payment.id),
            }

        payment.payment_status = PaymentStatus.FAILED.value
        payment.failed_at = now
        db.flush()
        logger.info("Renovación rechazada pago=%s code=%s", payment.id, code)
        return {
            "status": RENEWAL_DECLINED,
            "error": message,
            "payment_id": str(payment.id),
        }

    def _renewal_invoice(
        self,
        db: Session,
        account_id: UUID,
        subscription: Subscription,
        payment: Payment | None,
        subtotal: Decimal,
        tax_mxn: Decimal,
        total_mxn: Decimal,
    ) -> Invoice:
        """Reutiliza la factura del intento previo para no acumular folios."""
        invoice: Invoice | None = None
        if payment is not None and payment.invoice_id:
            invoice = db.query(Invoice).filter(Invoice.id == payment.invoice_id).first()
        if invoice is None:
            invoice = Invoice(
                account_id=account_id,
                organization_id=subscription.organization_id,
                subscription_id=subscription.id,
                invoice_number=next_invoice_number(db),
                currency="MXN",
            )
            db.add(invoice)
        invoice.invoice_status = InvoiceStatus.OPEN.value
        invoice.subtotal = subtotal
        invoice.discount_amount = Decimal("0")
        invoice.tax_amount = tax_mxn
        invoice.total_amount = total_mxn
        invoice.updated_at = datetime.now(timezone.utc)
        db.flush()
        return invoice

    def _renewal_payment(
        self,
        db: Session,
        account_id: UUID,
        subscription: Subscription,
        payment: Payment | None,
        invoice: Invoice,
        db_key: str,
        total_mxn: Decimal,
        pm: PaymentMethod,
        plan: Plan,
    ) -> Payment:
        """
        Un solo Payment por período renovado, reusado entre reintentos: el índice
        único de idempotency_key lo exige y el historial del cliente queda con el
        resultado final en vez de tres filas fallidas.
        """
        cycle = (subscription.billing_cycle or BillingCycle.MONTHLY.value).upper()
        extra = {
            "plan_id": str(plan.id),
            "billing_cycle": cycle,
            "renewal": True,
            "subscription_id": str(subscription.id),
        }
        if payment is None:
            payment = Payment(
                invoice_id=invoice.id,
                account_id=account_id,
                organization_id=subscription.organization_id,
                gateway=GATEWAY,
                idempotency_key=db_key,
                payment_method_type=PaymentMethodType.CARD.value,
                payment_method_id=pm.id,
                payment_method_meta={"brand": pm.brand, "last4": pm.last4},
                amount=total_mxn,
                currency="MXN",
                refunded_amount=Decimal("0"),
                payment_status=PaymentStatus.PENDING.value,
                extra_data=extra,
            )
            db.add(payment)
        else:
            payment.invoice_id = invoice.id
            payment.amount = total_mxn
            payment.payment_method_id = pm.id
            payment.payment_method_meta = {"brand": pm.brand, "last4": pm.last4}
            payment.payment_status = PaymentStatus.PENDING.value
            payment.gateway_payment_id = None
            payment.extra_data = {**(payment.extra_data or {}), **extra}
            payment.updated_at = datetime.now(timezone.utc)
        db.flush()
        return payment

    # ── Payment Methods ───────────────────────────────────────────────────────

    def list_payment_methods(self, db: Session, organization_id: UUID) -> list[dict]:
        account = self._get_account(db, organization_id)
        pms = (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.account_id == account.id,
                PaymentMethod.gateway == GATEWAY,
                PaymentMethod.is_active,
            )
            .order_by(PaymentMethod.is_default.desc(), PaymentMethod.created_at.desc())
            .all()
        )
        return [self._serialize_pm(pm) for pm in pms]

    def detach_payment_method(
        self, db: Session, organization_id: UUID, external_token: str
    ) -> None:
        account = self._get_account(db, organization_id)
        pm = self._assert_pm_ownership(db, external_token, account.id)

        if pm.is_default:
            count = (
                db.query(PaymentMethod)
                .filter(
                    PaymentMethod.account_id == account.id,
                    PaymentMethod.gateway == GATEWAY,
                    PaymentMethod.is_active,
                )
                .count()
            )
            if count <= 1:
                raise HTTPException(
                    400,
                    "No puedes eliminar el único método de pago. Agrega otro primero.",
                )
            raise HTTPException(
                400, "Asigna otro método como predeterminado antes de eliminar éste."
            )

        try:
            stripe.PaymentMethod.detach(external_token)
        except stripe.error.StripeError as e:
            logger.error("PaymentMethod.detach falló: %s", e.user_message)
            raise HTTPException(502, "Error al eliminar el método de pago")

        db.delete(pm)
        db.commit()
        logger.info("PM eliminado account=%s token=%s", account.id, external_token)

    def set_default_payment_method(
        self, db: Session, organization_id: UUID, external_token: str
    ) -> None:
        account = self._get_account(db, organization_id)
        new_default = self._assert_pm_ownership(db, external_token, account.id)

        if new_default.is_default:
            return

        now = datetime.now(timezone.utc)

        db.query(PaymentMethod).filter(
            PaymentMethod.account_id == account.id,
            PaymentMethod.gateway == GATEWAY,
            PaymentMethod.is_default,
        ).update({"is_default": False, "updated_at": now})

        try:
            cust = (
                db.query(PaymentGatewayCustomer)
                .filter(
                    PaymentGatewayCustomer.account_id == account.id,
                    PaymentGatewayCustomer.gateway == GATEWAY,
                )
                .first()
            )
            if cust:
                stripe.Customer.modify(
                    cust.external_customer_id,
                    invoice_settings={"default_payment_method": external_token},
                )
        except stripe.error.StripeError as e:
            logger.warning(
                "No se pudo actualizar default en Stripe Customer: %s", e.user_message
            )

        new_default.is_default = True
        new_default.updated_at = now
        db.commit()

    # ── Webhook ───────────────────────────────────────────────────────────────

    def handle_webhook(self, db: Session, payload: bytes, signature: str) -> None:
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, settings.STRIPE_WEBHOOK_SECRET
            )
            event = event.to_dict()
        except stripe.error.SignatureVerificationError:
            logger.warning("Webhook Stripe: firma inválida rechazada")
            raise HTTPException(400, "Firma de webhook inválida")
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Webhook parse error: %s", e)
            raise HTTPException(400, "Payload de webhook malformado")

        event_id: str = event["id"]
        event_type: str = event["type"]
        rec, claimed = self._claim_webhook_event(db, event)
        if not claimed:
            logger.info(
                "Evento duplicado ignorado: gateway=%s id=%s status=%s",
                GATEWAY,
                event_id,
                rec.event_status if rec else "missing",
            )
            return

        try:
            obj = event["data"]["object"]
            match event_type:
                case "setup_intent.succeeded":
                    self._on_setup_succeeded(db, obj)
                case "payment_intent.succeeded":
                    self._on_payment_succeeded(db, obj)
                case "payment_intent.payment_failed":
                    self._on_payment_failed(db, obj)
                case "payment_intent.canceled":
                    self._on_payment_canceled(db, obj)
                case "payment_intent.processing":
                    self._on_payment_status(db, obj, PaymentStatus.PROCESSING)
                case "payment_intent.requires_action":
                    self._on_payment_status(db, obj, PaymentStatus.REQUIRES_ACTION)
                case "charge.refunded":
                    self._on_charge_refunded(db, obj)
                case "charge.dispute.created" | "charge.dispute.updated":
                    self._on_dispute_opened(db, obj)
                case "charge.dispute.closed":
                    self._on_dispute_closed(db, obj)
                case "customer.subscription.updated":
                    self._on_sub_updated(db, obj)
                case "customer.subscription.deleted":
                    self._on_sub_deleted(db, obj)
                case "invoice.payment_failed":
                    logger.warning(
                        "Cobro automático fallido: sub=%s customer=%s",
                        obj.get("subscription"),
                        obj.get("customer"),
                    )
                case _:
                    rec.event_status = GatewayEventStatus.SKIPPED

            if rec.event_status != GatewayEventStatus.SKIPPED:
                rec.event_status = GatewayEventStatus.PROCESSED
            rec.error_message = None
            rec.processed_at = datetime.now(timezone.utc)
            db.commit()

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(
                "Error procesando evento %s (%s): %s", event_id, event_type, e
            )
            try:
                db.rollback()
            except Exception:
                pass
            self._mark_webhook_failed(db, event, e)
            raise HTTPException(500, "Error interno procesando webhook") from e

    def _claim_webhook_event(
        self, db: Session, event: dict
    ) -> tuple[PaymentGatewayEvent | None, bool]:
        event_id = event["id"]
        now = datetime.now(timezone.utc)
        existing = (
            db.query(PaymentGatewayEvent)
            .filter(
                PaymentGatewayEvent.gateway == GATEWAY,
                PaymentGatewayEvent.external_event_id == event_id,
            )
            .with_for_update()
            .first()
        )
        if existing is not None:
            return self._resume_claimed_event(db, existing, event, now)

        rec = PaymentGatewayEvent(
            gateway=GATEWAY,
            external_event_id=event_id,
            event_type=event["type"],
            event_status=GatewayEventStatus.PROCESSING,
            payload=self._webhook_payload_summary(event),
            processed_at=now,
        )
        try:
            with db.begin_nested():
                db.add(rec)
                db.flush()
            return rec, True
        except IntegrityError:
            sess = object_session(rec)
            if sess is not None:
                try:
                    sess.expunge(rec)
                except InvalidRequestError:
                    pass
            raced = (
                db.query(PaymentGatewayEvent)
                .filter(
                    PaymentGatewayEvent.gateway == GATEWAY,
                    PaymentGatewayEvent.external_event_id == event_id,
                )
                .with_for_update()
                .first()
            )
            if raced is None:
                raise HTTPException(500, "No se pudo reclamar el evento de webhook")
            return self._resume_claimed_event(db, raced, event, now)

    def _resume_claimed_event(
        self,
        db: Session,
        existing: PaymentGatewayEvent,
        event: dict,
        now: datetime,
    ) -> tuple[PaymentGatewayEvent, bool]:
        status_value = (
            existing.event_status.value
            if isinstance(existing.event_status, GatewayEventStatus)
            else str(existing.event_status)
        )
        if status_value in {"processed", "skipped"}:
            return existing, False

        if status_value == GatewayEventStatus.PROCESSING.value:
            processed_at = self._aware(existing.processed_at) or now
            if (now - processed_at).total_seconds() < 30:
                return existing, False

        existing.event_status = GatewayEventStatus.PROCESSING
        existing.event_type = event["type"]
        existing.payload = self._webhook_payload_summary(event)
        existing.error_message = None
        existing.processed_at = now
        existing.retry_count = (existing.retry_count or 0) + 1
        db.flush()
        return existing, True

    def _mark_webhook_failed(self, db: Session, event: dict, exc: Exception) -> None:
        event_id = event["id"]
        rec = db.get(PaymentGatewayEvent, (GATEWAY, event_id))
        if rec is None:
            rec = PaymentGatewayEvent(
                gateway=GATEWAY,
                external_event_id=event_id,
                event_type=event.get("type", "unknown"),
                event_status=GatewayEventStatus.FAILED,
                payload=self._webhook_payload_summary(event),
                error_message=str(exc)[:500],
                processed_at=datetime.now(timezone.utc),
                retry_count=1,
            )
            db.add(rec)
        else:
            rec.event_status = GatewayEventStatus.FAILED
            rec.error_message = str(exc)[:500]
            rec.processed_at = datetime.now(timezone.utc)
            rec.retry_count = (rec.retry_count or 0) + 1
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("No se pudo persistir webhook failed id=%s", event_id)

    def get_client_config(self) -> dict:
        return {
            "gateway": GATEWAY,
            "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        }

    # ── Handlers de eventos ───────────────────────────────────────────────────

    @staticmethod
    def _setup_pm_id(intent: dict) -> str | None:
        raw = intent.get("payment_method")
        if isinstance(raw, dict):
            raw = raw.get("id")
        if isinstance(raw, str) and raw.startswith("pm_"):
            return raw
        return None

    def _on_setup_succeeded(self, db: Session, intent: dict) -> None:
        self._persist_setup_payment_method(db, intent)

    def _persist_setup_payment_method(
        self, db: Session, intent: dict
    ) -> PaymentMethod | None:
        pm_id = self._setup_pm_id(intent)
        customer_id = intent.get("customer")
        if isinstance(customer_id, dict):
            customer_id = customer_id.get("id")
        if not pm_id or not customer_id:
            return None

        cust = (
            db.query(PaymentGatewayCustomer)
            .filter(
                PaymentGatewayCustomer.gateway == GATEWAY,
                PaymentGatewayCustomer.external_customer_id == customer_id,
            )
            .first()
        )
        if not cust:
            logger.error("Customer no encontrado en BD: %s", customer_id)
            return None

        existing = (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.gateway == GATEWAY, PaymentMethod.external_token == pm_id
            )
            .first()
        )
        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.updated_at = datetime.now(timezone.utc)
            return existing

        try:
            stripe_pm = stripe.PaymentMethod.retrieve(pm_id).to_dict()
        except stripe.error.StripeError as e:
            logger.error("No se pudo recuperar PM %s: %s", pm_id, e.user_message)
            return None

        card = stripe_pm.get("card", {})
        if not card:
            return None

        fingerprint = card.get("fingerprint")
        if fingerprint:
            existing_fp = (
                db.query(PaymentMethod)
                .filter(
                    PaymentMethod.account_id == cust.account_id,
                    PaymentMethod.gateway == GATEWAY,
                    PaymentMethod.fingerprint == fingerprint,
                    PaymentMethod.is_active,
                )
                .first()
            )
            if existing_fp:
                try:
                    stripe.PaymentMethod.detach(pm_id)
                except stripe.error.StripeError:
                    pass
                logger.info(
                    "PM duplicado rechazado y desadjuntado pm=%s fingerprint=%s account=%s",
                    pm_id,
                    fingerprint,
                    cust.account_id,
                )
                return existing_fp

        count = (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.account_id == cust.account_id,
                PaymentMethod.gateway == GATEWAY,
                PaymentMethod.is_active,
            )
            .count()
        )

        pm = PaymentMethod(
            account_id=cust.account_id,
            gateway=GATEWAY,
            external_token=pm_id,
            method_type=PaymentMethodType.CARD.value,
            brand=card.get("brand", "unknown"),
            last4=card.get("last4", "0000"),
            exp_month=card.get("exp_month", 1),
            exp_year=card.get("exp_year", 2099),
            fingerprint=fingerprint,
            is_default=(count == 0),
            is_active=True,
        )
        db.add(pm)
        db.flush()
        logger.info(
            "PM guardado gateway=%s account=%s brand=%s last4=%s fingerprint=%s",
            GATEWAY,
            cust.account_id,
            card.get("brand"),
            card.get("last4"),
            fingerprint,
        )
        return pm

    def _on_payment_succeeded(self, db: Session, pi: dict) -> None:
        pi_id = pi.get("id")
        payment = (
            db.query(Payment)
            .filter(Payment.gateway_payment_id == pi_id)
            .with_for_update()
            .first()
        )
        if not payment:
            logger.error("Payment no encontrado para PI: %s", pi_id)
            return
        self._fulfill_local_success(db, payment, pi)
        logger.info("Pago exitoso payment=%s pi=%s", payment.id, pi_id)

    def _fulfill_local_success(self, db: Session, payment: Payment, pi: dict) -> None:
        if payment.payment_status == PaymentStatus.SUCCESS.value:
            return

        now = datetime.now(timezone.utc)
        brand = self._extract_brand(pi)
        payment.payment_status = PaymentStatus.SUCCESS.value
        payment.succeeded_at = now
        payment.updated_at = now
        meta = dict(payment.payment_method_meta or {})
        if brand:
            meta["brand"] = brand
        payment.payment_method_meta = meta
        payment.provider_response = {
            "id": pi.get("id"),
            "status": pi.get("status"),
            "amount": pi.get("amount"),
            "brand": brand,
        }

        last4 = self._extract_last4(pi)
        receipt_url = self._extract_receipt_url(pi)
        if last4:
            meta["last4"] = last4
            payment.payment_method_meta = meta

        invoice = db.query(Invoice).filter(Invoice.id == payment.invoice_id).first()
        if invoice and invoice.invoice_status != InvoiceStatus.PAID.value:
            invoice.invoice_status = InvoiceStatus.PAID.value
            invoice.paid_at = now
            invoice.updated_at = now
        if invoice is not None and receipt_url:
            inv_extra = dict(invoice.extra_data or {})
            inv_extra["stripe_receipt_url"] = receipt_url
            invoice.extra_data = inv_extra

        metadata = pi.get("metadata") or {}
        extra = payment.extra_data or {}
        org_id = metadata.get("organization_id") or str(payment.organization_id)
        plan_id = metadata.get("plan_id") or extra.get("plan_id")
        billing_cycle = (
            metadata.get("billing_cycle")
            or extra.get("billing_cycle")
            or BillingCycle.MONTHLY.value
        )
        if not plan_id:
            raise RuntimeError(
                f"Pago {payment.id} sin plan_id en metadata; no se puede activar suscripción"
            )

        sub = self._activate_subscription(
            db, UUID(str(org_id)), UUID(str(plan_id)), billing_cycle
        )
        if invoice is not None and sub is not None:
            invoice.subscription_id = sub.id
        # Pagar levanta la suspensión por falta de pago, en la misma transacción:
        # si el pago se revierte, la reactivación también.
        reactivadas = suspension.reactivar_por_pago(
            db, UUID(str(org_id)), payment_id=payment.id
        )
        if reactivadas:
            logger.info("Pago %s reactivó %s", payment.id, reactivadas)
        db.flush()

    # ── Reembolsos y disputas ────────────────────────────────────────────────

    @staticmethod
    def _cents_to_mxn(cents: object) -> Decimal:
        try:
            return (Decimal(int(cents or 0)) / 100).quantize(Decimal("0.01"))
        except (TypeError, ValueError, ArithmeticError):
            return Decimal("0")

    @staticmethod
    def _from_unix(ts: object) -> datetime | None:
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    def _payment_for_charge(self, db: Session, obj: dict) -> Payment | None:
        """Ubica el Payment local a partir del payment_intent del cargo o disputa."""
        pi = obj.get("payment_intent")
        pi_id = pi.get("id") if isinstance(pi, dict) else pi
        if not pi_id:
            logger.error("Evento %s sin payment_intent asociado", obj.get("id"))
            return None
        payment = (
            db.query(Payment)
            .filter(Payment.gateway_payment_id == pi_id)
            .with_for_update()
            .first()
        )
        if payment is None:
            logger.error(
                "Payment no encontrado para PI %s (evento %s)", pi_id, obj.get("id")
            )
        return payment

    def _subscription_for_payment(
        self, db: Session, payment: Payment
    ) -> Subscription | None:
        """La suscripción que este pago activó, vía invoice.subscription_id."""
        if not payment.invoice_id:
            return None
        invoice = db.query(Invoice).filter(Invoice.id == payment.invoice_id).first()
        if invoice is None or not invoice.subscription_id:
            return None
        return (
            db.query(Subscription)
            .filter(Subscription.id == invoice.subscription_id)
            .with_for_update()
            .first()
        )

    def _shift_paid_period(self, db: Session, payment: Payment, now: datetime) -> None:
        """
        Quita de la vigencia el período que este pago compró, sin tocar los
        períodos de pagos anteriores. `period_revoked` en extra_data hace la
        operación idempotente ante webhooks repetidos.
        """
        extra = dict(payment.extra_data or {})
        if extra.get("period_revoked"):
            return

        sub = self._subscription_for_payment(db, payment)
        if sub is None:
            logger.warning(
                "Pago %s sin suscripción vinculada; no hay vigencia que revocar",
                payment.id,
            )
            extra["period_revoked"] = True
            payment.extra_data = extra
            return

        self._advisory_xact_lock(db, "sub", str(sub.organization_id))
        cycle = (
            extra.get("billing_cycle")
            or sub.billing_cycle
            or BillingCycle.MONTHLY.value
        ).upper()
        current_end = billing_period.as_aware(sub.expires_at) or now
        new_end = current_end - billing_period.cycle_duration(cycle)

        sub.expires_at = new_end
        sub.current_period_end = new_end
        if new_end <= now:
            sub.status = SubscriptionStatus.CANCELLED.value
            sub.cancelled_at = now
        sub.updated_at = now

        extra["period_revoked"] = True
        payment.extra_data = extra
        logger.warning(
            "Vigencia revocada sub=%s pago=%s nueva expiración=%s",
            sub.id,
            payment.id,
            new_end.isoformat(),
        )
        db.flush()

    def _restore_paid_period(
        self, db: Session, payment: Payment, now: datetime
    ) -> None:
        """Devuelve la vigencia retirada. Solo aplica si se había revocado."""
        extra = dict(payment.extra_data or {})
        if not extra.get("period_revoked"):
            return

        sub = self._subscription_for_payment(db, payment)
        if sub is not None:
            self._advisory_xact_lock(db, "sub", str(sub.organization_id))
            cycle = (
                extra.get("billing_cycle")
                or sub.billing_cycle
                or BillingCycle.MONTHLY.value
            ).upper()
            current_end = billing_period.as_aware(sub.expires_at) or now
            new_end = current_end + billing_period.cycle_duration(cycle)
            sub.expires_at = new_end
            sub.current_period_end = new_end
            if new_end > now:
                sub.status = SubscriptionStatus.ACTIVE.value
                sub.cancelled_at = None
            sub.updated_at = now
            logger.info(
                "Vigencia restaurada sub=%s pago=%s expiración=%s",
                sub.id,
                payment.id,
                new_end.isoformat(),
            )

        extra["period_revoked"] = False
        payment.extra_data = extra
        db.flush()

    def _close_invoice(
        self, db: Session, payment: Payment, status: str, now: datetime
    ) -> None:
        if not payment.invoice_id:
            return
        invoice = db.query(Invoice).filter(Invoice.id == payment.invoice_id).first()
        if invoice is None or invoice.invoice_status == status:
            return
        invoice.invoice_status = status
        if status == InvoiceStatus.PAID.value:
            invoice.paid_at = invoice.paid_at or now
        else:
            invoice.paid_at = None
        if status == InvoiceStatus.VOID.value:
            invoice.voided_at = now
        invoice.updated_at = now

    def _on_charge_refunded(self, db: Session, charge: dict) -> None:
        payment = self._payment_for_charge(db, charge)
        if payment is None:
            return

        now = datetime.now(timezone.utc)
        charged = Decimal(payment.amount or 0)
        # Stripe manda el acumulado devuelto, no el delta: se asigna, no se suma.
        refunded = min(self._cents_to_mxn(charge.get("amount_refunded")), charged)
        payment.refunded_amount = refunded
        payment.refunded_at = payment.refunded_at or now
        payment.updated_at = now

        fully_refunded = bool(charge.get("refunded")) or (
            charged > 0 and refunded >= charged
        )
        if not fully_refunded:
            payment.payment_status = PaymentStatus.PARTIALLY_REFUNDED.value
            logger.warning(
                "Reembolso parcial pago=%s devuelto=%s de %s",
                payment.id,
                refunded,
                charged,
            )
            return

        payment.payment_status = PaymentStatus.REFUNDED.value
        self._close_invoice(db, payment, InvoiceStatus.VOID.value, now)
        self._shift_paid_period(db, payment, now)
        logger.warning("Reembolso total pago=%s monto=%s", payment.id, refunded)

    def _on_dispute_opened(self, db: Session, dispute: dict) -> None:
        """
        Disputa abierta: se marca y se alerta, pero el servicio sigue. El cargo
        puede ganarse y cortarle a un cliente que no hizo nada sería peor.
        """
        payment = self._payment_for_charge(db, dispute)
        if payment is None:
            return

        now = datetime.now(timezone.utc)
        payment.is_disputed = True
        payment.dispute_id = dispute.get("id")
        payment.dispute_reason = dispute.get("reason")
        payment.dispute_status = dispute.get("status")
        payment.dispute_due_at = self._from_unix(
            (dispute.get("evidence_details") or {}).get("due_by")
        )
        if payment.payment_status == PaymentStatus.SUCCESS.value:
            payment.payment_status = PaymentStatus.DISPUTED.value
        payment.updated_at = now
        logger.warning(
            "DISPUTA abierta pago=%s dispute=%s razón=%s vence=%s",
            payment.id,
            payment.dispute_id,
            payment.dispute_reason,
            payment.dispute_due_at,
        )

    def _on_dispute_closed(self, db: Session, dispute: dict) -> None:
        payment = self._payment_for_charge(db, dispute)
        if payment is None:
            return

        now = datetime.now(timezone.utc)
        status = (dispute.get("status") or "").lower()
        payment.dispute_status = status
        payment.dispute_resolved_at = now
        payment.updated_at = now

        if status == "won":
            payment.is_disputed = False
            if payment.payment_status == PaymentStatus.DISPUTED.value:
                payment.payment_status = PaymentStatus.SUCCESS.value
            self._close_invoice(db, payment, InvoiceStatus.PAID.value, now)
            self._restore_paid_period(db, payment, now)
            logger.info("Disputa ganada pago=%s", payment.id)
            return

        if status == "lost":
            payment.payment_status = PaymentStatus.DISPUTED.value
            self._close_invoice(db, payment, InvoiceStatus.UNCOLLECTIBLE.value, now)
            self._shift_paid_period(db, payment, now)
            logger.warning("Disputa PERDIDA pago=%s: fondos retirados", payment.id)
            return

        logger.info("Disputa cerrada pago=%s con estado %s", payment.id, status)

    def _on_payment_failed(self, db: Session, pi: dict) -> None:
        payment = (
            db.query(Payment)
            .filter(Payment.gateway_payment_id == pi.get("id"))
            .with_for_update()
            .first()
        )
        if not payment or payment.payment_status != PaymentStatus.PENDING.value:
            return

        error = pi.get("last_payment_error", {}) or {}
        payment.payment_status = PaymentStatus.FAILED.value
        payment.failed_at = datetime.now(timezone.utc)
        payment.failure_code = error.get("code")
        payment.failure_message = error.get("message")
        logger.info("Pago fallido payment=%s", payment.id)

    def _on_payment_canceled(self, db: Session, pi: dict) -> None:
        payment = (
            db.query(Payment)
            .filter(Payment.gateway_payment_id == pi.get("id"))
            .with_for_update()
            .first()
        )
        if not payment or payment.payment_status != PaymentStatus.PENDING.value:
            return
        payment.payment_status = PaymentStatus.CANCELED.value
        payment.canceled_at = datetime.now(timezone.utc)

    def _on_payment_status(
        self, db: Session, pi: dict, new_status: PaymentStatus
    ) -> None:
        payment = (
            db.query(Payment)
            .filter(Payment.gateway_payment_id == pi.get("id"))
            .with_for_update()
            .first()
        )
        if not payment or payment.payment_status == PaymentStatus.SUCCESS.value:
            return
        if payment.payment_status == PaymentStatus.PENDING.value:
            payment.payment_status = new_status.value

    def _on_sub_updated(self, db: Session, sub: dict) -> None:
        record = (
            db.query(Subscription)
            .filter(Subscription.external_id == sub.get("id"))
            .first()
        )
        if not record:
            return
        status_map = {
            "active": SubscriptionStatus.ACTIVE.value,
            "canceled": SubscriptionStatus.CANCELLED.value,
            "past_due": SubscriptionStatus.ACTIVE.value,
            "unpaid": SubscriptionStatus.CANCELLED.value,
        }
        s = sub.get("status", "")
        if s in status_map:
            record.status = status_map[s]
        if end := sub.get("current_period_end"):
            record.expires_at = datetime.fromtimestamp(end, tz=timezone.utc)

    def _on_sub_deleted(self, db: Session, sub: dict) -> None:
        record = (
            db.query(Subscription)
            .filter(Subscription.external_id == sub.get("id"))
            .first()
        )
        if record:
            record.status = SubscriptionStatus.CANCELLED.value
            record.cancelled_at = datetime.now(timezone.utc)

    def _activate_subscription(
        self, db: Session, organization_id: UUID, plan_id: UUID, billing_cycle: str
    ) -> Subscription:
        now = datetime.now(timezone.utc)
        cycle = billing_cycle.upper()
        # Serializa por organización: dos webhooks simultáneos leerían el mismo
        # fin de período y al encadenar el segundo pisaría al primero, dejando al
        # cliente con un período menos del que pagó.
        self._advisory_xact_lock(db, "sub", str(organization_id))
        existing = subscription_query.get_primary_active_subscription(
            db, organization_id
        )
        if existing:
            # Renovar el mismo plan encadena el período; cambiar de plan lo
            # reinicia hoy, porque lo que se contrató es otra cosa.
            same_plan = (
                str(existing.plan_id) == str(plan_id)
                and (existing.billing_cycle or "").upper() == cycle
            )
            start, expires = billing_period.next_period(
                cycle,
                now=now,
                current_end=(
                    existing.current_period_end or existing.expires_at
                    if same_plan
                    else None
                ),
            )
            existing.plan_id = plan_id
            existing.billing_cycle = cycle
            existing.status = SubscriptionStatus.ACTIVE.value
            existing.expires_at = expires
            existing.current_period_start = start
            existing.current_period_end = expires
            existing.updated_at = now
            db.flush()
            return existing

        _, expires = billing_period.next_period(cycle, now=now)

        sub = Subscription(
            plan_id=plan_id,
            organization_id=organization_id,
            status=SubscriptionStatus.ACTIVE.value,
            started_at=now,
            expires_at=expires,
            billing_cycle=cycle,
            auto_renew=True,
            current_period_start=now,
            current_period_end=expires,
        )
        db.add(sub)
        db.flush()
        return sub

    @staticmethod
    def _serialize_pm(pm: PaymentMethod) -> dict:
        now = datetime.now(timezone.utc)
        expired = pm.exp_year is not None and (
            pm.exp_year < now.year
            or (pm.exp_year == now.year and (pm.exp_month or 0) < now.month)
        )
        return {
            "id": str(pm.id),
            "gateway": pm.gateway,
            "external_token": pm.external_token,
            "type": pm.method_type,
            "brand": pm.brand,
            "last4": pm.last4,
            "exp_month": pm.exp_month,
            "exp_year": pm.exp_year,
            "is_default": pm.is_default,
            "is_expired": expired,
            "metadata": pm.extra_data,
            "created_at": pm.created_at.isoformat(),
        }

    @staticmethod
    def _pi_as_dict(pi: stripe.PaymentIntent) -> dict:
        if hasattr(pi, "to_dict"):
            return pi.to_dict()
        return {
            "id": getattr(pi, "id", None),
            "status": getattr(pi, "status", None),
            "amount": getattr(pi, "amount", None),
            "metadata": getattr(pi, "metadata", {}) or {},
            "charges": getattr(pi, "charges", None) or {"data": []},
            "latest_charge": getattr(pi, "latest_charge", None),
        }

    @staticmethod
    def _charge_from_pi(pi: dict) -> dict:
        charges = (pi.get("charges") or {}).get("data") or []
        if charges and isinstance(charges[0], dict):
            return charges[0]
        charge = pi.get("latest_charge")
        return charge if isinstance(charge, dict) else {}

    @staticmethod
    def _extract_brand(pi: dict) -> str:
        card = (
            StripeGateway._charge_from_pi(pi).get("payment_method_details") or {}
        ).get("card") or {}
        return card.get("brand") or "card"

    @staticmethod
    def _extract_last4(pi: dict) -> str | None:
        card = (
            StripeGateway._charge_from_pi(pi).get("payment_method_details") or {}
        ).get("card") or {}
        last4 = card.get("last4")
        return str(last4) if last4 else None

    @staticmethod
    def _extract_receipt_url(pi: dict) -> str | None:
        url = StripeGateway._charge_from_pi(pi).get("receipt_url")
        if isinstance(url, str) and url.startswith("https://"):
            return url
        return None

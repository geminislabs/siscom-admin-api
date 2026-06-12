# app/services/gateways/stripe_gateway.py
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import stripe
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
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
from app.services import subscription_query

logger = logging.getLogger(__name__)

GATEWAY = "stripe"


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
        db.commit()
        db.refresh(rec)
        logger.info(
            "Stripe Customer creado account=%s customer_id=%s", account_id, customer.id
        )
        return rec.external_customer_id

    # ── Setup Intent ──────────────────────────────────────────────────────────

    def create_setup_intent(self, db: Session, organization_id: UUID) -> dict:
        """
        Inicia el flujo de guardado de tarjeta.
        Devuelve client_token para que Stripe.js monte el Payment Element.
        Idempotency key por bucket de hora → reintentos en la misma sesión
        reusan el mismo SetupIntent sin crear duplicados en Stripe.
        """
        account = self._get_account(db, organization_id)
        customer_id = self.get_or_create_customer(
            db, account.id, account.billing_email or "", account.name
        )

        try:
            intent = stripe.SetupIntent.create(
                customer=customer_id,
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
                usage="off_session",
                metadata={"account_id": str(account.id)},
            )
        except stripe.error.StripeError as e:
            logger.error("SetupIntent.create falló: %s", e.user_message)
            raise HTTPException(502, "Error al inicializar el guardado de tarjeta")

        return {"client_token": intent.client_secret, "gateway": GATEWAY}

    # ── Payment Intent ────────────────────────────────────────────────────────

    def create_payment_intent(
        self, db: Session, organization_id: UUID, plan_id: UUID, billing_cycle: str
    ) -> dict:
        """
        Crea un PaymentIntent para el pago de una suscripción.

        SEGURIDAD: El monto proviene de la tabla plans en la BD.
        El frontend envía plan_id + billing_cycle, NUNCA el monto.

        IDEMPOTENCIA: La key es sha256(account + plan + ciclo + mes/año).
        Mismo pago en el mismo mes → mismo PaymentIntent en Stripe.
        """
        account = self._get_account(db, organization_id)
        customer_id = self.get_or_create_customer(
            db, account.id, account.billing_email or "", account.name
        )

        plan = db.query(Plan).filter(Plan.id == plan_id, Plan.is_active).first()
        if not plan:
            raise HTTPException(404, "Plan no encontrado o inactivo")

        amount_mxn = (
            plan.price_yearly
            if billing_cycle.upper() == BillingCycle.YEARLY.value
            else plan.price_monthly
        )
        amount_cents = int(float(amount_mxn) * 100)
        if amount_cents <= 0:
            raise HTTPException(400, "El plan no tiene precio configurado")

        period = datetime.now(timezone.utc).strftime("%Y%m")
        idem = self._idem_key(
            "pi", str(account.id), str(plan_id), billing_cycle.upper(), period
        )

        # Clave de idempotencia hacia Stripe (puede diferir de `idem` si hay que reemitir PI).
        stripe_pi_idempotency_key = idem
        # Fila de Payment a reutilizar cuando el PI previo en Stripe ya no sirve (p. ej. canceled).
        payment_row_to_refresh: Payment | None = None

        # ── Idempotencia BD + reuse de PI vigente ─────────────────────────────
        existing = db.query(Payment).filter(Payment.idempotency_key == idem).first()
        if existing:
            if existing.payment_status == PaymentStatus.SUCCESS.value:
                raise HTTPException(
                    409, "Este pago ya fue procesado exitosamente este período"
                )
            if existing.gateway_payment_id:
                try:
                    prior_pi = stripe.PaymentIntent.retrieve(
                        existing.gateway_payment_id
                    )
                    if prior_pi.status != "canceled":
                        return self._pi_response(prior_pi, existing, plan)
                    # Mismo `idem` en Stripe devolvería otra vez este PI cancelado → nueva clave + actualizar fila.
                    stripe_pi_idempotency_key = self._idem_key(
                        idem, "stripe_reissue", existing.gateway_payment_id
                    )
                    payment_row_to_refresh = existing
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

        # ── Cancelar PIs pendientes de otros planes ───────────────────────────
        # Garantiza un solo intento de pago activo por account a la vez.
        # Si el usuario intentó pagar Plan A y ahora intenta Plan B,
        # el PI del Plan A se cancela antes de crear el nuevo.
        stale = (
            db.query(Payment)
            .filter(
                Payment.account_id == account.id,
                Payment.payment_status == PaymentStatus.PENDING.value,
                Payment.idempotency_key != idem,
            )
            .all()
        )
        for p in stale:
            if p.gateway_payment_id:
                try:
                    stripe.PaymentIntent.cancel(p.gateway_payment_id)
                except stripe.error.InvalidRequestError:
                    pass  # ya cancelado o en estado no cancelable
                except stripe.error.StripeError as exc:
                    logger.warning(
                        "No se pudo cancelar PI %s: %s", p.gateway_payment_id, exc
                    )
            p.payment_status = PaymentStatus.CANCELED.value
            if p.invoice_id:
                inv = db.query(Invoice).filter(Invoice.id == p.invoice_id).first()
                if inv:
                    inv.invoice_status = InvoiceStatus.VOID.value
        if stale:
            db.flush()

        # ── PM predeterminado ─────────────────────────────────────────────────
        default_pm = (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.account_id == account.id,
                PaymentMethod.gateway == GATEWAY,
                PaymentMethod.is_default,
                PaymentMethod.is_active,
            )
            .first()
        )

        # ── Crear Stripe PaymentIntent ────────────────────────────────────────
        try:
            # DESPUÉS (corregido):
            pi_params: dict = {
                "amount": amount_cents,
                "currency": "mxn",
                "customer": customer_id,
                "confirm": False,
                "automatic_payment_methods": {
                    "enabled": True,
                    "allow_redirects": "never",  # evita redirect 3DS innecesario, paga inline
                },
                "setup_future_usage": "off_session",
                "metadata": {
                    "account_id": str(account.id),
                    "organization_id": str(organization_id),
                    "plan_id": str(plan_id),
                    "plan_code": plan.code or "",
                    "billing_cycle": billing_cycle.upper(),
                },
            }
            if default_pm:
                pi_params["payment_method"] = default_pm.external_token

            pi = stripe.PaymentIntent.create(
                **pi_params, idempotency_key=stripe_pi_idempotency_key
            )
        except stripe.error.StripeError as e:
            logger.error("PaymentIntent.create falló: %s", e.user_message)
            raise HTTPException(502, "Error al inicializar el pago")

        # Mismo PI en Stripe pero fila BD sin nuestra idempotencia (o ENUM gateway) → igual hay colisión única en `gateway_payment_id`.
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
                raise HTTPException(
                    409, "Este pago ya fue procesado exitosamente este período"
                )
            if conflict_db.idempotency_key != idem:
                conflict_db.idempotency_key = idem
            db.commit()
            db.refresh(conflict_db)
            return self._pi_response(pi, conflict_db, plan)

        # ── Crear Invoice + Payment (o refrescar intento tras PI cancelado) ────
        year = datetime.now(timezone.utc).year
        count = (
            db.query(func.count(Invoice.id))
            .filter(Invoice.account_id == account.id)
            .scalar()
            or 0
        )
        invoice_number = f"INV-{year}-{count + 1:04d}"

        invoice = Invoice(
            account_id=account.id,
            organization_id=organization_id,
            invoice_number=invoice_number,
            invoice_status=InvoiceStatus.OPEN.value,
            subtotal=amount_mxn,
            discount_amount=Decimal("0"),
            tax_amount=Decimal("0"),
            total_amount=amount_mxn,
            currency="MXN",
        )
        db.add(invoice)

        payment: Payment
        if payment_row_to_refresh:
            payment = payment_row_to_refresh
            if payment.invoice_id:
                prev_inv = (
                    db.query(Invoice).filter(Invoice.id == payment.invoice_id).first()
                )
                if prev_inv:
                    prev_inv.invoice_status = InvoiceStatus.VOID.value
            db.flush()  # asignar id de `invoice`
            payment.invoice_id = invoice.id
            payment.gateway_payment_id = pi.id
            payment.amount = amount_mxn
            payment.payment_status = PaymentStatus.PENDING.value
            payment.payment_method_id = default_pm.id if default_pm else None
            payment.refunded_amount = Decimal("0")
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
                payment_method_id=default_pm.id if default_pm else None,
                payment_method_meta={},
                amount=amount_mxn,
                currency="MXN",
                refunded_amount=Decimal("0"),
                payment_status=PaymentStatus.PENDING.value,
            )
            db.add(payment)
        try:
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
                return self._pi_response(pi, reused, plan)
            raise HTTPException(
                409,
                "Este intento ya está registrado. Recarga la página y vuelve a intentarlo.",
            ) from exc

        return self._pi_response(pi, payment, plan)

    @staticmethod
    def _pi_response(pi: stripe.PaymentIntent, payment: Payment, plan: Plan) -> dict:
        return {
            "client_token": pi.client_secret,
            "gateway": GATEWAY,
            "payment_id": str(payment.id),
            "amount_mxn": float(payment.amount),
            "amount_with_iva": round(float(payment.amount) * 1.16, 2),
            "plan_name": plan.name,
            "plan_code": plan.code,
        }

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
        except Exception as e:
            logger.error("Webhook parse error: %s", e)
            raise HTTPException(400, "Payload de webhook malformado")

        event_id: str = event["id"]
        event_type: str = event["type"]

        if db.get(PaymentGatewayEvent, (GATEWAY, event_id)):
            logger.info(
                "Evento duplicado ignorado: gateway=%s id=%s", GATEWAY, event_id
            )
            return

        rec = PaymentGatewayEvent(
            gateway=GATEWAY,
            external_event_id=event_id,
            event_type=event_type,
            event_status=GatewayEventStatus.PROCESSED,
            payload={
                "type": event_type,
                "created": event.get("created"),
                "livemode": event.get("livemode"),
            },
        )
        db.add(rec)

        try:
            obj = event["data"]["object"]
            match event_type:
                case "setup_intent.succeeded":
                    self._on_setup_succeeded(db, obj)
                case "payment_intent.succeeded":
                    self._on_payment_succeeded(db, obj)
                case "payment_intent.payment_failed":
                    self._on_payment_failed(db, obj)
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

            db.commit()

        except Exception as e:
            logger.error("Error procesando evento %s (%s): %s", event_id, event_type, e)
            rec.event_status = GatewayEventStatus.FAILED
            rec.error_message = str(e)[:500]
            try:
                db.commit()
            except Exception:
                db.rollback()

    def get_client_config(self) -> dict:
        return {
            "gateway": GATEWAY,
            "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        }

    # ── Handlers de eventos ───────────────────────────────────────────────────

    def _on_setup_succeeded(self, db: Session, intent: dict) -> None:
        pm_id = intent.get("payment_method")
        customer_id = intent.get("customer")
        if not pm_id or not customer_id:
            return

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
            return

        # Dedup por external_token (mismo objeto PM)
        if (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.gateway == GATEWAY, PaymentMethod.external_token == pm_id
            )
            .first()
        ):
            return

        try:
            stripe_pm = stripe.PaymentMethod.retrieve(pm_id).to_dict()
        except stripe.error.StripeError as e:
            logger.error("No se pudo recuperar PM %s: %s", pm_id, e.user_message)
            return

        card = stripe_pm.get("card", {})
        if not card:
            return

        # Dedup por fingerprint (misma tarjeta, distinto pm_xxx)
        fingerprint = card.get("fingerprint")
        if fingerprint and (
            db.query(PaymentMethod)
            .filter(
                PaymentMethod.account_id == cust.account_id,
                PaymentMethod.gateway == GATEWAY,
                PaymentMethod.fingerprint == fingerprint,
                PaymentMethod.is_active,
            )
            .first()
        ):
            # Desadjuntar el PM duplicado de Stripe para no acumular basura
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
            return

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
        logger.info(
            "PM guardado gateway=%s account=%s brand=%s last4=%s fingerprint=%s",
            GATEWAY,
            cust.account_id,
            card.get("brand"),
            card.get("last4"),
            fingerprint,
        )

    def _on_payment_succeeded(self, db: Session, pi: dict) -> None:
        pi_id = pi.get("id")
        metadata = pi.get("metadata", {})

        payment = db.query(Payment).filter(Payment.gateway_payment_id == pi_id).first()
        if not payment or payment.payment_status == PaymentStatus.SUCCESS.value:
            return

        now = datetime.now(timezone.utc)
        payment.payment_status = PaymentStatus.SUCCESS.value
        payment.succeeded_at = now
        payment.payment_method_type = self._extract_brand(pi)
        payment.provider_response = {
            "id": pi_id,
            "status": pi.get("status"),
            "amount": pi.get("amount"),
        }

        invoice = db.query(Invoice).filter(Invoice.id == payment.invoice_id).first()
        if invoice:
            invoice.invoice_status = InvoiceStatus.PAID.value
            invoice.paid_at = now

        org_id = metadata.get("organization_id")
        plan_id = metadata.get("plan_id")
        billing_cycle = metadata.get("billing_cycle", BillingCycle.MONTHLY.value)

        if org_id and plan_id:
            try:
                self._activate_subscription(
                    db, UUID(org_id), UUID(plan_id), billing_cycle
                )
            except Exception as e:
                logger.error("Error activando suscripción: %s", e)

        logger.info("Pago exitoso payment=%s pi=%s", payment.id, pi_id)

    def _on_payment_failed(self, db: Session, pi: dict) -> None:
        payment = (
            db.query(Payment).filter(Payment.gateway_payment_id == pi.get("id")).first()
        )
        if not payment or payment.payment_status != PaymentStatus.PENDING.value:
            return

        error = pi.get("last_payment_error", {}) or {}
        payment.payment_status = PaymentStatus.FAILED.value
        payment.failed_at = datetime.now(timezone.utc)
        payment.failure_code = error.get("code")
        payment.failure_message = error.get("message")
        logger.info("Pago fallido payment=%s", payment.id)

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
    ) -> None:
        now = datetime.now(timezone.utc)
        expires = now + (
            timedelta(days=365)
            if billing_cycle.upper() == BillingCycle.YEARLY.value
            else timedelta(days=30)
        )
        existing = subscription_query.get_primary_active_subscription(
            db, organization_id
        )
        if existing:
            existing.status = SubscriptionStatus.ACTIVE.value
            existing.expires_at = expires
            existing.current_period_start = now
            existing.current_period_end = expires
            existing.updated_at = now
        else:
            sub = Subscription(
                plan_id=plan_id,
                organization_id=organization_id,
                status=SubscriptionStatus.ACTIVE.value,
                started_at=now,
                expires_at=expires,
                billing_cycle=billing_cycle.upper(),
                auto_renew=True,
                current_period_start=now,
                current_period_end=expires,
            )
            db.add(sub)

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
    def _extract_brand(pi: dict) -> str:
        charges = pi.get("charges", {}).get("data", [])
        if charges:
            return (
                charges[0]
                .get("payment_method_details", {})
                .get("card", {})
                .get("brand", "card")
            )
        return "card"

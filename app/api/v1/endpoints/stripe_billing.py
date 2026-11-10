# app/api/v1/endpoints/stripe_billing.py

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_organization_id_facturacion,
    get_current_user_full_facturacion,
)
from app.db.session import get_db
from app.models.organization import Organization
from app.models.plan import Plan
from app.models.user import User
from app.services import billing_period, subscription_query
from app.services.gateways import registry
from app.services.idempotency_service import (
    PAYMENT_INTENT_ENDPOINT,
    abandon_idempotency,
    begin_idempotency,
    canonical_request_hash,
    complete_idempotency,
    require_idempotency_key,
)
from app.services.organization import OrganizationService

router = APIRouter()
logger = logging.getLogger(__name__)


class PaymentIntentRequest(BaseModel):
    """
    El cliente solo elige qué plan y ciclo. El monto lo calcula el backend
    desde `plans`; campos extra (amount, total, etc.) se rechazan.
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    billing_cycle: str
    gateway: str = "stripe"

    @field_validator("billing_cycle")
    @classmethod
    def validate_cycle(cls, v: str) -> str:
        v = v.upper()
        if v not in {"MONTHLY", "YEARLY"}:
            raise ValueError("billing_cycle debe ser MONTHLY o YEARLY")
        return v

    @field_validator("gateway")
    @classmethod
    def validate_gw(cls, v: str) -> str:
        return v.lower()


class ConfirmSetupRequest(BaseModel):
    setup_intent_id: str
    gateway: str = "stripe"

    @field_validator("gateway")
    @classmethod
    def validate_gw(cls, v: str) -> str:
        return v.lower()

    @field_validator("setup_intent_id")
    @classmethod
    def validate_si(cls, v: str) -> str:
        v = (v or "").strip()
        # Stripe SetupIntent ids are seti_… (pi_ is PaymentIntent; si_ does not exist).
        if not v.startswith("seti_") or len(v) > 255 or any(c.isspace() for c in v):
            raise ValueError("setup_intent_id inválido")
        return v


class SetDefaultPMRequest(BaseModel):
    external_token: str
    gateway: str = "stripe"

    @field_validator("gateway")
    @classmethod
    def validate_gw(cls, v: str) -> str:
        return v.lower()


class AutoRenewRequest(BaseModel):
    auto_renew: bool


def _http_exc_body(exc: HTTPException) -> dict:
    if isinstance(exc.detail, dict):
        return exc.detail
    return {"detail": exc.detail}


def _account_id_for_org(db: Session, organization_id: UUID) -> UUID:
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(404, "Organización no encontrada")
    if not org.account_id:
        raise HTTPException(400, "La organización no tiene cuenta comercial asociada")
    return org.account_id


def _require_billing_permission(
    db: Session,
    current_user: User,
    organization_id: UUID,
) -> None:
    """
    Solo owner y billing pueden gestionar pagos.
    Usa OrganizationService.can_manage_billing como fuente de verdad.
    """
    if not OrganizationService.can_manage_billing(db, current_user.id, organization_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar facturación. "
            "Se requiere rol owner o billing.",
        )


@router.get("/config")
def get_payment_config(
    gateway: str = Query(default=None),
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
):
    """
    Configuración pública de la pasarela para el frontend (requiere JWT).
    Stripe   → { "publishable_key": "pk_...", "gateway": "stripe" }
    PayPal   → { "client_id": "...", "gateway": "paypal" }
    También retorna la lista de pasarelas disponibles.
    La publishable key NO está hardcodeada en el frontend.
    """
    if gateway:
        config = registry.get(gateway.lower()).get_client_config()
    else:
        config = registry.get_default().get_client_config()

    return {**config, "available_gateways": registry.available()}


@router.get("/quote")
def quote_plan(
    plan_id: UUID,
    billing_cycle: str = Query(..., description="MONTHLY o YEARLY"),
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """
    Cotización oficial del cobro. La interfaz la muestra; nunca la calcula.

    Sin esto, el cliente tendría que aplicar IVA y redondear, y un usuario
    malicioso podría mostrar un precio y confirmar otro.
    """
    del organization_id, current_user
    cycle = billing_cycle.upper()
    if cycle not in {"MONTHLY", "YEARLY"}:
        raise HTTPException(400, "billing_cycle debe ser MONTHLY o YEARLY")
    plan = db.query(Plan).filter(Plan.id == plan_id, Plan.is_active).first()
    if not plan:
        raise HTTPException(404, "Plan no encontrado o inactivo")
    return billing_period.quote_plan(plan, cycle)


@router.post("/setup-intent", status_code=201)
def create_setup_intent(
    gateway: str = Query(default="stripe"),
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """
    Inicia el flujo de guardado de tarjeta.
    Devuelve client_token para que Stripe.js monte el Payment Element.
    El PAN NUNCA llega a nuestros servidores.
    """
    _require_billing_permission(db, current_user, organization_id)
    return registry.get(gateway.lower()).create_setup_intent(db, organization_id)


@router.post("/payment-intent", status_code=201)
def create_payment_intent(
    body: PaymentIntentRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """
    Crea un intento de cobro para el plan indicado.

    SEGURIDAD: El monto se calcula en backend desde tabla plans.
    El frontend envía SOLO: plan_id + billing_cycle + gateway.
    El monto NUNCA viene del frontend.

    Idempotency-Key (obligatoria): reserva atómica por cuenta.
    Distinta de la key determinista que el backend envía a Stripe.
    """
    _require_billing_permission(db, current_user, organization_id)

    account_id = _account_id_for_org(db, organization_id)
    request_hash = canonical_request_hash(
        {
            "plan_id": str(body.plan_id),
            "billing_cycle": body.billing_cycle,
            "gateway": body.gateway,
        }
    )
    reservation = begin_idempotency(
        db,
        idempotency_key,
        account_id,
        PAYMENT_INTENT_ENDPOINT,
        request_hash,
    )
    if reservation.cached:
        return JSONResponse(
            status_code=reservation.cached.status_code,
            content=reservation.cached.body,
        )

    try:
        result = registry.get(body.gateway).create_payment_intent(
            db, organization_id, body.plan_id, body.billing_cycle
        )
    except HTTPException as exc:
        if 400 <= exc.status_code < 500:
            complete_idempotency(db, reservation, exc.status_code, _http_exc_body(exc))
        else:
            abandon_idempotency(db, reservation)
        raise
    except Exception:
        logger.exception("create_payment_intent falló")
        abandon_idempotency(db, reservation)
        raise HTTPException(
            500, "No se pudo inicializar el pago. Intenta de nuevo."
        ) from None

    complete_idempotency(db, reservation, 201, result)
    return result


@router.get("/payment-methods")
def list_payment_methods(
    gateway: str = Query(default="stripe"),
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """Lista métodos de pago guardados del account para la pasarela indicada."""
    _require_billing_permission(db, current_user, organization_id)
    return registry.get(gateway.lower()).list_payment_methods(db, organization_id)


@router.post("/payment-methods/confirm")
def confirm_setup_intent(
    body: ConfirmSetupRequest,
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """
    Persiste una tarjeta ya confirmada por Stripe.js.

    El webhook hace lo mismo; este endpoint no espera a Stripe Listen.
    El cliente solo envía el id del SetupIntent; el servidor lo verifica.
    """
    _require_billing_permission(db, current_user, organization_id)
    gw = registry.get(body.gateway)
    confirm = getattr(gw, "confirm_setup_intent", None)
    if confirm is None:
        raise HTTPException(400, "Esta pasarela no confirma tarjetas de este modo")
    return confirm(db, organization_id, body.setup_intent_id)


@router.delete("/payment-methods/{external_token}", status_code=204)
def delete_payment_method(
    external_token: str,
    gateway: str = Query(default="stripe"),
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """
    Elimina un método de pago.
    La pasarela valida que el método pertenece al account (anti-IDOR).
    """
    _require_billing_permission(db, current_user, organization_id)
    registry.get(gateway.lower()).detach_payment_method(
        db, organization_id, external_token
    )


@router.patch("/payment-methods/default")
def set_default_payment_method(
    body: SetDefaultPMRequest,
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """Establece un método de pago como predeterminado."""
    _require_billing_permission(db, current_user, organization_id)
    registry.get(body.gateway).set_default_payment_method(
        db, organization_id, body.external_token
    )
    return {"ok": True}


@router.patch("/auto-renew")
def set_auto_renew(
    body: AutoRenewRequest,
    organization_id: UUID = Depends(get_current_organization_id_facturacion),
    current_user: User = Depends(get_current_user_full_facturacion),
    db: Session = Depends(get_db),
):
    """
    Activa o desactiva la renovación automática de la suscripción vigente.

    Apagarla no cancela nada: la suscripción sigue vigente hasta su fecha de
    vencimiento y simplemente no se vuelve a cobrar.
    """
    _require_billing_permission(db, current_user, organization_id)
    sub = subscription_query.get_primary_active_subscription(db, organization_id)
    if sub is None:
        raise HTTPException(404, "No tienes una suscripción activa")

    sub.auto_renew = body.auto_renew
    if body.auto_renew:
        # Reactivar limpia el dunning previo: si la tarjeta era el problema y ya
        # la cambió, no tiene por qué esperar al reintento agendado.
        sub.dunning_next_attempt = None
        sub.dunning_attempt_count = 0
        sub.renewal_last_error = None
    sub.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"auto_renew": sub.auto_renew, "expires_at": sub.expires_at}


@router.post(
    "/webhook/{gateway}",
    status_code=200,
    include_in_schema=False,  # No exponer en docs públicos
)
async def payment_webhook(
    gateway: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Recibe webhooks de todas las pasarelas por un único endpoint.

    URL por pasarela:
      Stripe → /api/v1/stripe/webhook/stripe

    SIN JWT — la firma del cuerpo es la autenticación.
    Firma inválida → 400. Duplicado / evento no manejado → 200.
    Fallo transitorio de fulfillment → 5xx para que Stripe reintente.

    Cada pasarela usa su propio header de firma:
      Stripe → stripe-signature
    """
    payload = await request.body()

    signature = (
        request.headers.get("stripe-signature")
        or request.headers.get("paypal-transmission-sig")
        or ""
    )

    registry.get(gateway.lower()).handle_webhook(db, payload, signature)
    return {"received": True}

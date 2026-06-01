# app/api/v1/endpoints/stripe_billing.py

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization_id, get_current_user_full
from app.db.session import get_db
from app.models.user import User
from app.services.gateways import registry
from app.services.organization import OrganizationService

logger = logging.getLogger(__name__)
router = APIRouter()

class PaymentIntentRequest(BaseModel):
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


class SetDefaultPMRequest(BaseModel):
    external_token: str
    gateway: str = "stripe"

    @field_validator("gateway")
    @classmethod
    def validate_gw(cls, v: str) -> str:
        return v.lower()

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
    organization_id: UUID = Depends(get_current_organization_id),
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


@router.post("/setup-intent", status_code=201)
def create_setup_intent(
    gateway: str = Query(default="stripe"),
    organization_id: UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user_full),
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
    organization_id: UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user_full),
    db: Session = Depends(get_db),
):
    """
    Crea un intento de cobro para el plan indicado.

    SEGURIDAD: El monto se calcula en backend desde tabla plans.
    El frontend envía SOLO: plan_id + billing_cycle + gateway.
    El monto NUNCA viene del frontend.
    """
    _require_billing_permission(db, current_user, organization_id)
    return registry.get(body.gateway).create_payment_intent(
        db, organization_id, body.plan_id, body.billing_cycle
    )

@router.get("/payment-methods")
def list_payment_methods(
    gateway: str = Query(default="stripe"),
    organization_id: UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user_full),
    db: Session = Depends(get_db),
):
    """Lista métodos de pago guardados del account para la pasarela indicada."""
    _require_billing_permission(db, current_user, organization_id)
    return registry.get(gateway.lower()).list_payment_methods(db, organization_id)


@router.delete("/payment-methods/{external_token}", status_code=204)
def delete_payment_method(
    external_token: str,
    gateway: str = Query(default="stripe"),
    organization_id: UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user_full),
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
    organization_id: UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user_full),
    db: Session = Depends(get_db),
):
    """Establece un método de pago como predeterminado."""
    _require_billing_permission(db, current_user, organization_id)
    registry.get(body.gateway).set_default_payment_method(
        db, organization_id, body.external_token
    )
    return {"ok": True}

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
    Responde siempre 200 para evitar reintentos infinitos.

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

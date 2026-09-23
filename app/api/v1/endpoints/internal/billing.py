"""
Endpoints internos de billing para GAC (pagos manuales).

Requiere: Token PASETO con service="gac" y role="GAC_ADMIN"
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_solo_servicio
from app.db.session import get_db
from app.schemas.manual_payment import ManualPaymentCreate, ManualPaymentResponse
from app.services import renewal_service
from app.services.manual_payment_service import register_manual_payment

router = APIRouter()

get_auth_for_internal_billing = get_auth_solo_servicio(
    required_service="gac",
    required_role="GAC_ADMIN",
)


@router.post(
    "/manual-payments",
    response_model=ManualPaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_manual_payment(
    body: ManualPaymentCreate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_billing),
):
    """
    Registra un pago en efectivo y activa (o renueva) la suscripción de la organización.
    """
    gac_operator_id = auth.payload.get("internal_id") if auth.payload else None
    return register_manual_payment(db, body, gac_operator_id=gac_operator_id)


@router.post("/renewals/run", status_code=status.HTTP_200_OK)
def run_renewals(
    limit: int = Query(
        renewal_service.DEFAULT_BATCH_LIMIT,
        ge=1,
        le=1000,
        description="Tope de suscripciones a procesar en esta corrida",
    ),
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_billing),
):
    """
    Cobra las renovaciones que ya toca intentar. Diseñado para un cron diario.

    Es seguro llamarlo varias veces: el cobro es idempotente por período
    renovado y los reintentos rechazados quedan agendados, no se repiten en la
    misma corrida.
    """
    return renewal_service.run_renewals(db, limit=limit).as_dict()

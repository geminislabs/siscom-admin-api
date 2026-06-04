"""
Endpoints internos de billing para GAC (pagos manuales).

Requiere: Token PASETO con service="gac" y role="GAC_ADMIN"
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_cognito_or_paseto
from app.db.session import get_db
from app.schemas.manual_payment import ManualPaymentCreate, ManualPaymentResponse
from app.services.manual_payment_service import register_manual_payment

router = APIRouter()

get_auth_for_internal_billing = get_auth_cognito_or_paseto(
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

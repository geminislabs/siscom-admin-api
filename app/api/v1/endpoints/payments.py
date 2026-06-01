# app/api/v1/endpoints/payments.py
"""
Endpoints de pagos (read-only, compatibilidad).

NOTA: El listado detallado con paginación y filtros vive en
      GET /billing/payments (billing.py).
      Este endpoint se mantiene como alias paginado simple
      para compatibilidad con clientes que ya consumen /payments.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization_id
from app.db.session import get_db
from app.models.organization import Organization
from app.models.payment import Payment, PaymentStatus
from app.schemas.payment import PaymentOut

router = APIRouter()


def _resolve_account_id(db: Session, organization_id: UUID) -> Optional[UUID]:
    org = db.query(Organization.account_id).filter(Organization.id == organization_id).first()
    return org.account_id if org else None


@router.get("", response_model=List[PaymentOut])
def list_payments(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    status: Optional[PaymentStatus] = Query(default=None),
):
    """
    Lista pagos de la organización autenticada.
    Usa account_id resuelto desde la organización — nunca client_id (deprecado).
    """
    account_id = _resolve_account_id(db, organization_id)
    if not account_id:
        return []

    query = db.query(Payment).filter(Payment.account_id == account_id)

    if status:
        query = query.filter(Payment.status == status.value)

    return (
        query
        .order_by(Payment.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

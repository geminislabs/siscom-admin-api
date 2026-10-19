from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full
from app.db.session import get_db
from app.models.alert import Alert
from app.models.organization import Organization, OrganizationStatus
from app.models.unit import Unit
from app.models.user import User
from app.models.user_unit import UserUnit
from app.schemas.alert import AlertOut
from app.services.access_control import get_accessible_unit_ids

router = APIRouter()


def _validate_unit_access(db: Session, user: User, unit_id: UUID) -> None:
    unit = (
        db.query(Unit)
        .filter(
            Unit.id == unit_id,
            Unit.organization_id == user.organization_id,
            Unit.deleted_at.is_(None),
        )
        .first()
    )

    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unidad no encontrada",
        )

    if user.is_active_organization_owner:
        return

    user_unit = (
        db.query(UserUnit)
        .join(Unit, Unit.id == UserUnit.unit_id)
        .filter(
            UserUnit.user_id == user.id,
            UserUnit.unit_id == unit_id,
            Unit.organization_id == user.organization_id,
            Unit.deleted_at.is_(None),
        )
        .first()
    )

    if not user_unit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a esta unidad",
        )


def _organization_is_active(db: Session, organization_id: UUID) -> bool:
    org = (
        db.query(Organization)
        .filter(
            Organization.id == organization_id,
            Organization.status == OrganizationStatus.ACTIVE,
        )
        .first()
    )
    return org is not None


@router.get("", response_model=list[AlertOut])
def list_alerts(
    unit_id: UUID | None = Query(None, description="ID de la unidad"),
    type_filter: str | None = Query(None, alias="type"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    if not _organization_is_active(db, current_user.organization_id):
        return []

    query = db.query(Alert).filter(
        Alert.organization_id == current_user.organization_id
    )

    if unit_id is not None:
        _validate_unit_access(db, current_user, unit_id)
        query = query.filter(Alert.unit_id == unit_id)
    else:
        accessible_unit_ids = get_accessible_unit_ids(db, current_user)
        if not accessible_unit_ids:
            return []

        query = query.filter(Alert.unit_id.in_(accessible_unit_ids))

        # Si no se envía unit_id, el endpoint devuelve las últimas 20 alertas
        # visibles para el usuario autenticado, ignorando paginación de entrada.
        limit = 20
        offset = 0

    query = query.order_by(Alert.occurred_at.desc())

    if type_filter:
        query = query.filter(Alert.type == type_filter)

    if date_from:
        query = query.filter(Alert.occurred_at >= date_from)

    if date_to:
        query = query.filter(Alert.occurred_at <= date_to)

    return query.offset(offset).limit(limit).all()

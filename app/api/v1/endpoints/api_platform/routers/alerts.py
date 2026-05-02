from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization_id
from app.api.v1.endpoints.api_platform.schemas.alerts import (
    AlertCreate,
    AlertOut,
    AlertUpdate,
)
from app.api.v1.endpoints.api_platform.services.alerts import AlertService
from app.db.session import get_db

router = APIRouter()


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
def create_alert(
    data: AlertCreate,
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return AlertService.create(db, org_id, data)


@router.get("", response_model=list[AlertOut])
def list_alerts(
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return AlertService.list(db, org_id)


@router.patch("/{alert_id}", response_model=AlertOut)
def update_alert(
    alert_id: UUID,
    data: AlertUpdate,
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return AlertService.update(db, alert_id, org_id, data)

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.endpoints.api_platform.models.api_alert import ApiAlert
from app.api.v1.endpoints.api_platform.models.api_throttle import ApiThrottleEvent
from app.api.v1.endpoints.api_platform.repositories.alerts import (
    AlertRepository,
    ThrottleRepository,
)
from app.api.v1.endpoints.api_platform.schemas.alerts import AlertCreate, AlertUpdate


class AlertService:
    @staticmethod
    def create(
        db: Session, organization_id: UUID, data: AlertCreate
    ) -> ApiAlert:
        alert = ApiAlert(
            id=uuid4(),
            organization_id=organization_id,
            api_key_id=data.api_key_id,
            type=data.type,
            threshold=data.threshold,
            time_window=data.time_window,
            enabled=True,
        )
        return AlertRepository.create(db, alert)

    @staticmethod
    def list(db: Session, organization_id: UUID) -> list[ApiAlert]:
        return AlertRepository.list_by_org(db, organization_id)

    @staticmethod
    def update(
        db: Session, alert_id: UUID, organization_id: UUID, data: AlertUpdate
    ) -> ApiAlert:
        alert = AlertRepository.get_by_id(db, alert_id, organization_id)
        if not alert:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found"
            )
        alert.enabled = data.enabled
        return AlertRepository.update(db, alert)


class ThrottleService:
    @staticmethod
    def list(
        db: Session,
        organization_id: UUID,
        type_filter: Optional[str] = None,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApiThrottleEvent]:
        return ThrottleRepository.list_by_org(
            db,
            organization_id,
            type_filter=type_filter,
            from_dt=from_dt,
            to_dt=to_dt,
            limit=limit,
            offset=offset,
        )

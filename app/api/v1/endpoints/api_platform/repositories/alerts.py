from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.v1.endpoints.api_platform.models.api_alert import ApiAlert
from app.api.v1.endpoints.api_platform.models.api_throttle import ApiThrottleEvent


class AlertRepository:
    @staticmethod
    def create(db: Session, alert: ApiAlert) -> ApiAlert:
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert

    @staticmethod
    def get_by_id(
        db: Session, alert_id: UUID, organization_id: UUID
    ) -> Optional[ApiAlert]:
        return (
            db.query(ApiAlert)
            .filter(
                ApiAlert.id == alert_id,
                ApiAlert.organization_id == organization_id,
            )
            .first()
        )

    @staticmethod
    def list_by_org(db: Session, organization_id: UUID) -> list[ApiAlert]:
        return (
            db.query(ApiAlert)
            .filter(ApiAlert.organization_id == organization_id)
            .order_by(ApiAlert.created_at.desc())
            .all()
        )

    @staticmethod
    def update(db: Session, alert: ApiAlert) -> ApiAlert:
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert


class ThrottleRepository:
    @staticmethod
    def list_by_org(
        db: Session,
        organization_id: UUID,
        type_filter: Optional[str] = None,
        from_dt=None,
        to_dt=None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApiThrottleEvent]:
        q = db.query(ApiThrottleEvent).filter(
            ApiThrottleEvent.organization_id == organization_id
        )
        if type_filter:
            q = q.filter(ApiThrottleEvent.type == type_filter)
        if from_dt:
            q = q.filter(ApiThrottleEvent.created_at >= from_dt)
        if to_dt:
            q = q.filter(ApiThrottleEvent.created_at <= to_dt)
        return (
            q.order_by(ApiThrottleEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

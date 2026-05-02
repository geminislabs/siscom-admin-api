from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization_id
from app.api.v1.endpoints.api_platform.schemas.usage import (
    LimitsStatus,
    TimeseriesPoint,
    UsageByKeyItem,
    UsageSummary,
)
from app.api.v1.endpoints.api_platform.services.usage import UsageService
from app.db.session import get_db

router = APIRouter()


@router.get("/summary", response_model=UsageSummary)
def usage_summary(
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return UsageService.get_summary(db, org_id)


@router.get("/by-key", response_model=list[UsageByKeyItem])
def usage_by_key(
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return UsageService.get_by_key(db, org_id)


@router.get("/timeseries", response_model=list[TimeseriesPoint])
def usage_timeseries(
    from_dt: datetime = Query(..., alias="from"),
    to_dt: datetime = Query(..., alias="to"),
    granularity: Literal["minute", "day", "month"] = Query("day"),
    api_key_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    if from_dt >= to_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'from' must be before 'to'",
        )
    return UsageService.get_timeseries(db, org_id, from_dt, to_dt, granularity, api_key_id)


@router.get("/limits", response_model=LimitsStatus)
def usage_limits(
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    plan_id = _resolve_plan_id(db, org_id)
    return UsageService.get_limits(db, org_id, plan_id)


def _resolve_plan_id(db: Session, organization_id: UUID) -> Optional[UUID]:
    """Resolve the active plan_id for the organization via subscriptions."""
    from app.models.subscription import Subscription

    sub = (
        db.query(Subscription)
        .filter(
            Subscription.organization_id == organization_id,
            Subscription.status == "ACTIVE",
        )
        .order_by(Subscription.created_at.desc())
        .first()
    )
    return sub.plan_id if sub else None

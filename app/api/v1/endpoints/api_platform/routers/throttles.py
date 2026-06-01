from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization_id
from app.api.v1.endpoints.api_platform.services.alerts import ThrottleService
from app.db.session import get_db

router = APIRouter()


class ThrottleEventOut(BaseModel):
    id: UUID
    api_key_id: Optional[UUID]
    organization_id: Optional[UUID]
    type: str
    limit_value: Optional[int]
    actual_value: Optional[int]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ThrottleEventOut])
def list_throttle_events(
    type: Optional[str] = Query(None, pattern="^(RPM_LIMIT|DAILY_LIMIT|BURST)$"),
    from_dt: Optional[datetime] = Query(None, alias="from"),
    to_dt: Optional[datetime] = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return ThrottleService.list(
        db,
        org_id,
        type_filter=type,
        from_dt=from_dt,
        to_dt=to_dt,
        limit=limit,
        offset=offset,
    )

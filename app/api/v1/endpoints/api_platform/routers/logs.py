from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization_id
from app.api.v1.endpoints.api_platform.schemas.logs import LogsPage, LogsStats
from app.api.v1.endpoints.api_platform.services.logs import LogService
from app.db.session import get_db

router = APIRouter()


@router.get("", response_model=LogsPage)
def list_logs(
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    api_key_id: Optional[UUID] = Query(None),
    status_code: Optional[int] = Query(None),
    method: Optional[str] = Query(None),
    endpoint: Optional[str] = Query(None),
    from_dt: Optional[datetime] = Query(None, alias="from"),
    to_dt: Optional[datetime] = Query(None, alias="to"),
    ip: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return LogService.list(
        db=db,
        organization_id=org_id,
        limit=limit,
        cursor=cursor,
        api_key_id=api_key_id,
        status_code=status_code,
        method=method,
        endpoint=endpoint,
        from_dt=from_dt,
        to_dt=to_dt,
        ip=ip,
    )


@router.get("/stats", response_model=LogsStats)
def logs_stats(
    db: Session = Depends(get_db),
    org_id: UUID = Depends(get_current_organization_id),
):
    return LogService.get_stats(db, org_id)

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.v1.endpoints.api_platform.repositories.logs import LogRepository
from app.api.v1.endpoints.api_platform.schemas.logs import LogEntry, LogsPage, LogsStats


class LogService:
    @staticmethod
    def list(
        db: Session,
        organization_id: UUID,
        limit: int = 50,
        cursor: Optional[str] = None,
        api_key_id: Optional[UUID] = None,
        status_code: Optional[int] = None,
        method: Optional[str] = None,
        endpoint: Optional[str] = None,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        ip: Optional[str] = None,
    ) -> LogsPage:
        rows, next_cursor = LogRepository.list_cursor(
            db=db,
            organization_id=organization_id,
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
        return LogsPage(
            items=[LogEntry.model_validate(r) for r in rows],
            next_cursor=next_cursor,
            limit=limit,
        )

    @staticmethod
    def get_stats(db: Session, organization_id: UUID) -> LogsStats:
        raw = LogRepository.get_stats(db, organization_id)
        return LogsStats(
            requests_today=raw["requests_today"],
            success_rate=raw["success_rate"],
            p50_latency_ms=raw["p50_latency_ms"],
            errors_24h=raw["errors_24h"],
        )

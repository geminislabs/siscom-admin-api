import base64
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import case, func, text
from sqlalchemy.orm import Session

from app.api.v1.endpoints.api_platform.models.api_log import ApiRequestLog


def _encode_cursor(created_at: datetime, row_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, id_str = raw.split("|", 1)
    return datetime.fromisoformat(ts_str), UUID(id_str)


class LogRepository:
    @staticmethod
    def list_cursor(
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
    ) -> tuple[list[ApiRequestLog], Optional[str]]:
        q = db.query(ApiRequestLog).filter(
            ApiRequestLog.organization_id == organization_id
        )

        if cursor:
            cursor_time, cursor_id = _decode_cursor(cursor)
            q = q.filter(
                (ApiRequestLog.created_at < cursor_time)
                | (
                    (ApiRequestLog.created_at == cursor_time)
                    & (ApiRequestLog.id < cursor_id)
                )
            )

        if api_key_id:
            q = q.filter(ApiRequestLog.api_key_id == api_key_id)
        if status_code is not None:
            q = q.filter(ApiRequestLog.status_code == status_code)
        if method:
            q = q.filter(ApiRequestLog.method == method.upper())
        if endpoint:
            q = q.filter(ApiRequestLog.endpoint.ilike(f"%{endpoint}%"))
        if from_dt:
            q = q.filter(ApiRequestLog.created_at >= from_dt)
        if to_dt:
            q = q.filter(ApiRequestLog.created_at <= to_dt)
        if ip:
            q = q.filter(ApiRequestLog.ip == ip)

        rows = (
            q.order_by(
                ApiRequestLog.created_at.desc(), ApiRequestLog.id.desc()
            )
            .limit(limit + 1)
            .all()
        )

        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last.created_at, last.id)

        return rows, next_cursor

    @staticmethod
    def get_stats(db: Session, organization_id: UUID) -> dict:
        now = datetime.now(tz=timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        last_24h = now - timedelta(hours=24)

        today_counts = (
            db.query(
                func.count(ApiRequestLog.id).label("total"),
                func.sum(
                    case((ApiRequestLog.status_code < 400, 1), else_=0)
                ).label("success"),
            )
            .filter(
                ApiRequestLog.organization_id == organization_id,
                ApiRequestLog.created_at >= start_of_day,
            )
            .first()
        )

        errors_24h = (
            db.query(func.count(ApiRequestLog.id))
            .filter(
                ApiRequestLog.organization_id == organization_id,
                ApiRequestLog.created_at >= last_24h,
                ApiRequestLog.status_code >= 400,
            )
            .scalar()
        ) or 0

        p50 = (
            db.execute(
                text(
                    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) "
                    "FROM api_platform.api_request_logs "
                    "WHERE organization_id = :org_id AND created_at >= :since"
                ),
                {"org_id": str(organization_id), "since": start_of_day},
            ).scalar()
        )

        total = today_counts.total or 0
        success = int(today_counts.success or 0)
        success_rate = success / total if total > 0 else 1.0

        return {
            "requests_today": total,
            "success_rate": round(success_rate, 4),
            "p50_latency_ms": float(p50) if p50 is not None else None,
            "errors_24h": int(errors_24h),
        }

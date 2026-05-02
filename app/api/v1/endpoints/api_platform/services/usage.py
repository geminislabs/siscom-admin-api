from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.v1.endpoints.api_platform.repositories.keys import ApiKeyRepository
from app.api.v1.endpoints.api_platform.repositories.usage import UsageRepository
from app.api.v1.endpoints.api_platform.schemas.usage import (
    LimitsStatus,
    TimeseriesPoint,
    UsageByKeyItem,
    UsageSummary,
)


class UsageService:
    @staticmethod
    def get_summary(db: Session, organization_id: UUID) -> UsageSummary:
        active_keys = ApiKeyRepository.count_active(db, organization_id)
        requests_today = UsageRepository.get_requests_today(db, organization_id)
        errors_today = UsageRepository.get_errors_today(db, organization_id)
        requests_month = UsageRepository.get_requests_month(db, organization_id)

        error_rate = errors_today / requests_today if requests_today > 0 else 0.0

        return UsageSummary(
            active_keys=active_keys,
            requests_today=requests_today,
            requests_month=requests_month,
            error_rate=round(error_rate, 4),
        )

    @staticmethod
    def get_by_key(db: Session, organization_id: UUID) -> list[UsageByKeyItem]:
        keys = ApiKeyRepository.list_by_org(db, organization_id)
        key_map = {k.id: k.name for k in keys}

        rows = UsageRepository.get_by_key_today(db, organization_id)
        total = sum(r[1] for r in rows) or 1

        return [
            UsageByKeyItem(
                api_key_id=r[0],
                name=key_map.get(r[0], "unknown"),
                requests=r[1],
                percentage=round(r[1] / total * 100, 2),
            )
            for r in rows
        ]

    @staticmethod
    def get_timeseries(
        db: Session,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        granularity: Literal["minute", "day", "month"],
        api_key_id: Optional[UUID] = None,
    ) -> list[TimeseriesPoint]:
        if granularity == "minute":
            rows = UsageRepository.get_timeseries_minute(
                db, organization_id, from_dt, to_dt, api_key_id
            )
            return [
                TimeseriesPoint(
                    bucket=r.bucket,
                    request_count=r.request_count,
                    error_count=r.error_count,
                )
                for r in rows
            ]
        elif granularity == "day":
            rows = UsageRepository.get_timeseries_daily(
                db,
                organization_id,
                from_dt.date(),
                to_dt.date(),
                api_key_id,
            )
            return [
                TimeseriesPoint(
                    bucket=datetime.combine(r.day, datetime.min.time()),
                    request_count=r.request_count,
                    error_count=r.error_count,
                )
                for r in rows
            ]
        else:  # month
            rows = UsageRepository.get_timeseries_monthly(
                db,
                organization_id,
                from_dt.date().replace(day=1),
                to_dt.date().replace(day=1),
                api_key_id,
            )
            return [
                TimeseriesPoint(
                    bucket=datetime.combine(r.month, datetime.min.time()),
                    request_count=r.request_count,
                    error_count=r.error_count,
                )
                for r in rows
            ]

    @staticmethod
    def get_limits(
        db: Session, organization_id: UUID, plan_id: Optional[UUID]
    ) -> LimitsStatus:
        limits = None
        if plan_id:
            limits = UsageRepository.get_limits_by_plan(db, plan_id)

        keys = ApiKeyRepository.list_by_org(db, organization_id, status="ACTIVE")
        key_ids = [k.id for k in keys]
        counters = UsageRepository.get_counters_for_org(db, key_ids)

        rpm_current = sum(c.current_minute_count or 0 for c in counters)
        daily_current = sum(c.current_day_count or 0 for c in counters)
        monthly_current = sum(c.current_month_count or 0 for c in counters)

        return LimitsStatus(
            rpm_limit=limits.rpm_limit if limits else None,
            rpm_current=rpm_current,
            daily_limit=limits.daily_limit if limits else None,
            daily_current=daily_current,
            monthly_limit=limits.monthly_limit if limits else None,
            monthly_current=monthly_current,
            burst_limit=limits.burst_limit if limits else None,
            burst_current=None,
        )

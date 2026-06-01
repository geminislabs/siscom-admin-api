from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.endpoints.api_platform.models.api_limit import ApiLimit
from app.api.v1.endpoints.api_platform.models.api_usage import (
    ApiUsageCounter,
    ApiUsageDaily,
    ApiUsageMinute,
    ApiUsageMonthly,
)


class UsageRepository:
    @staticmethod
    def get_requests_today(db: Session, organization_id: UUID) -> int:
        today = date.today()
        result = (
            db.query(func.coalesce(func.sum(ApiUsageDaily.request_count), 0))
            .filter(
                ApiUsageDaily.organization_id == organization_id,
                ApiUsageDaily.day == today,
            )
            .scalar()
        )
        return int(result)

    @staticmethod
    def get_errors_today(db: Session, organization_id: UUID) -> int:
        today = date.today()
        result = (
            db.query(func.coalesce(func.sum(ApiUsageDaily.error_count), 0))
            .filter(
                ApiUsageDaily.organization_id == organization_id,
                ApiUsageDaily.day == today,
            )
            .scalar()
        )
        return int(result)

    @staticmethod
    def get_requests_month(db: Session, organization_id: UUID) -> int:
        first_of_month = date.today().replace(day=1)
        result = (
            db.query(func.coalesce(func.sum(ApiUsageMonthly.request_count), 0))
            .filter(
                ApiUsageMonthly.organization_id == organization_id,
                ApiUsageMonthly.month == first_of_month,
            )
            .scalar()
        )
        return int(result)

    @staticmethod
    def get_errors_month(db: Session, organization_id: UUID) -> int:
        first_of_month = date.today().replace(day=1)
        result = (
            db.query(func.coalesce(func.sum(ApiUsageMonthly.error_count), 0))
            .filter(
                ApiUsageMonthly.organization_id == organization_id,
                ApiUsageMonthly.month == first_of_month,
            )
            .scalar()
        )
        return int(result)

    @staticmethod
    def get_by_key_today(db: Session, organization_id: UUID) -> list[tuple[UUID, int]]:
        today = date.today()
        rows = (
            db.query(ApiUsageDaily.api_key_id, ApiUsageDaily.request_count)
            .filter(
                ApiUsageDaily.organization_id == organization_id,
                ApiUsageDaily.day == today,
            )
            .all()
        )
        return rows

    @staticmethod
    def get_timeseries_minute(
        db: Session,
        organization_id: UUID,
        from_dt: datetime,
        to_dt: datetime,
        api_key_id: Optional[UUID] = None,
    ) -> list[ApiUsageMinute]:
        q = db.query(ApiUsageMinute).filter(
            ApiUsageMinute.organization_id == organization_id,
            ApiUsageMinute.bucket >= from_dt,
            ApiUsageMinute.bucket <= to_dt,
        )
        if api_key_id:
            q = q.filter(ApiUsageMinute.api_key_id == api_key_id)
        return q.order_by(ApiUsageMinute.bucket).all()

    @staticmethod
    def get_timeseries_daily(
        db: Session,
        organization_id: UUID,
        from_date: date,
        to_date: date,
        api_key_id: Optional[UUID] = None,
    ) -> list[ApiUsageDaily]:
        q = db.query(ApiUsageDaily).filter(
            ApiUsageDaily.organization_id == organization_id,
            ApiUsageDaily.day >= from_date,
            ApiUsageDaily.day <= to_date,
        )
        if api_key_id:
            q = q.filter(ApiUsageDaily.api_key_id == api_key_id)
        return q.order_by(ApiUsageDaily.day).all()

    @staticmethod
    def get_timeseries_monthly(
        db: Session,
        organization_id: UUID,
        from_date: date,
        to_date: date,
        api_key_id: Optional[UUID] = None,
    ) -> list[ApiUsageMonthly]:
        q = db.query(ApiUsageMonthly).filter(
            ApiUsageMonthly.organization_id == organization_id,
            ApiUsageMonthly.month >= from_date,
            ApiUsageMonthly.month <= to_date,
        )
        if api_key_id:
            q = q.filter(ApiUsageMonthly.api_key_id == api_key_id)
        return q.order_by(ApiUsageMonthly.month).all()

    @staticmethod
    def get_counters_for_org(
        db: Session, api_key_ids: list[UUID]
    ) -> list[ApiUsageCounter]:
        if not api_key_ids:
            return []
        return (
            db.query(ApiUsageCounter)
            .filter(ApiUsageCounter.api_key_id.in_(api_key_ids))
            .all()
        )

    @staticmethod
    def get_limits_by_plan(db: Session, plan_id: UUID) -> Optional[ApiLimit]:
        return db.query(ApiLimit).filter(ApiLimit.plan_id == plan_id).first()

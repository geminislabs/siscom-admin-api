"""Resumen de suscripción Nexus activa por account u organización."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.plan import Plan
from app.models.subscription import Subscription, SubscriptionStatus
from app.services.subscription_query import get_primary_active_subscription

INACTIVE_SUMMARY = {
    "nexus_service_status": "inactive",
    "active_subscription_id": None,
    "active_plan_id": None,
    "active_plan_name": None,
    "active_plan_code": None,
    "active_organization_id": None,
    "active_organization_name": None,
    "billing_cycle": None,
    "active_units": None,
    "expires_at": None,
}


def _summary_from_subscription(
    sub: Subscription, plan: Plan, org: Organization
) -> dict:
    return {
        "nexus_service_status": "active",
        "active_subscription_id": str(sub.id),
        "active_plan_id": str(sub.plan_id),
        "active_plan_name": plan.name,
        "active_plan_code": plan.code,
        "active_organization_id": str(org.id),
        "active_organization_name": org.name,
        "billing_cycle": sub.billing_cycle,
        "active_units": getattr(sub, "active_units", None),
        "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
    }


def get_account_nexus_status(db: Session, account_id: UUID) -> dict:
    """
    Suscripción Nexus vigente más reciente entre las organizaciones del account.
    """
    orgs = (
        db.query(Organization)
        .filter(Organization.account_id == account_id)
        .order_by(Organization.created_at.asc())
        .all()
    )
    if not orgs:
        return dict(INACTIVE_SUMMARY)

    best: Optional[tuple[Subscription, Organization]] = None
    for org in orgs:
        sub = get_primary_active_subscription(db, org.id)
        if not sub:
            continue
        if best is None or sub.started_at > best[0].started_at:
            best = (sub, org)

    if not best:
        return dict(INACTIVE_SUMMARY)

    sub, org = best
    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
    if not plan:
        return dict(INACTIVE_SUMMARY)

    return _summary_from_subscription(sub, plan, org)


def get_accounts_nexus_status_map(
    db: Session, account_ids: list[UUID]
) -> dict[UUID, dict]:
    """Mapa account_id → resumen Nexus (una query para listados)."""
    if not account_ids:
        return {}

    now = datetime.utcnow()
    rows = (
        db.query(Subscription, Plan, Organization)
        .join(Organization, Subscription.organization_id == Organization.id)
        .join(Plan, Subscription.plan_id == Plan.id)
        .filter(
            Organization.account_id.in_(account_ids),
            Subscription.status.in_(
                [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIAL.value]
            ),
            or_(Subscription.expires_at > now, Subscription.expires_at.is_(None)),
        )
        .order_by(Organization.account_id, Subscription.started_at.desc())
        .all()
    )

    result: dict[UUID, dict] = {aid: dict(INACTIVE_SUMMARY) for aid in account_ids}
    seen: set[UUID] = set()
    for sub, plan, org in rows:
        aid = org.account_id
        if aid in seen:
            continue
        seen.add(aid)
        result[aid] = _summary_from_subscription(sub, plan, org)
    return result


def get_organization_nexus_status(db: Session, organization_id: UUID) -> dict:
    """Estado Nexus de una sola organización."""
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        return dict(INACTIVE_SUMMARY)

    sub = get_primary_active_subscription(db, organization_id)
    if not sub:
        return dict(INACTIVE_SUMMARY)

    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
    if not plan:
        return dict(INACTIVE_SUMMARY)

    return _summary_from_subscription(sub, plan, org)

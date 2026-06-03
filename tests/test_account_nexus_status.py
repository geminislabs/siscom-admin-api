"""Tests para resumen Nexus por account."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.models.organization import Organization
from app.models.plan import Plan
from app.models.subscription import Subscription, SubscriptionStatus
from app.services.account_nexus_status import get_account_nexus_status


def test_account_inactive_without_subscription(db_session, test_account_data, test_organization_data):
    summary = get_account_nexus_status(db_session, test_account_data.id)
    assert summary["nexus_service_status"] == "inactive"
    assert summary["active_subscription_id"] is None


def test_account_active_with_subscription(db_session, test_account_data, test_organization_data):
    plan = Plan(
        id=uuid4(),
        name="TrackGo",
        code="trackgo",
        price_monthly=Decimal("299"),
        price_yearly=Decimal("2990"),
        is_active=True,
    )
    db_session.add(plan)
    now = datetime.now(timezone.utc)
    sub = Subscription(
        id=uuid4(),
        organization_id=test_organization_data.id,
        plan_id=plan.id,
        status=SubscriptionStatus.ACTIVE.value,
        started_at=now,
        expires_at=now + timedelta(days=30),
        billing_cycle="MONTHLY",
        active_units=2,
    )
    db_session.add(sub)
    db_session.commit()

    summary = get_account_nexus_status(db_session, test_account_data.id)
    assert summary["nexus_service_status"] == "active"
    assert summary["active_plan_code"] == "trackgo"
    assert summary["active_units"] == 2

"""Tests de comportamiento en modelos Capability / Subscription (sin BD)."""

from datetime import datetime, timedelta
from uuid import uuid4

from app.models.capability import OrganizationCapability, PlanCapability
from app.models.subscription import SubscriptionStatus


def test_plan_capability_get_value_priority():
    pc = PlanCapability(
        plan_id=uuid4(),
        capability_id=uuid4(),
        value_int=10,
        value_bool=True,
        value_text=None,
    )
    assert pc.get_value() == 10


def test_organization_capability_is_expired():
    oc = OrganizationCapability(
        id=uuid4(),
        organization_id=uuid4(),
        capability_id=uuid4(),
        value_int=1,
        expires_at=datetime(2020, 1, 1),
    )
    assert oc.is_expired() is True


def test_organization_capability_not_expired_when_no_expires_at():
    oc = OrganizationCapability(
        id=uuid4(),
        organization_id=uuid4(),
        capability_id=uuid4(),
        value_int=1,
        expires_at=None,
    )
    assert oc.is_expired() is False


def test_subscription_status_enum_values():
    assert SubscriptionStatus.ACTIVE.value == "ACTIVE"

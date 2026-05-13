"""Tests para app.services.subscription_query (regla única de suscripción activa)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.subscription_query import (
    count_active_subscriptions,
    get_active_plan_id,
    get_active_subscriptions,
    get_active_subscriptions_for_client,
    get_primary_active_subscription,
    get_primary_active_subscription_for_client,
    get_subscription_history,
    has_active_subscription,
    has_active_subscription_for_client,
)


def test_get_active_subscriptions_uses_builder_query_all():
    db = MagicMock()
    oid = uuid4()
    subs = [MagicMock(), MagicMock()]

    mock_q = MagicMock()
    mock_q.all.return_value = subs

    with patch(
        "app.services.subscription_query._build_active_subscriptions_query",
        return_value=mock_q,
    ):
        assert get_active_subscriptions(db, oid) == subs


def test_get_primary_active_subscription_returns_first_ordered():
    db = MagicMock()
    oid = uuid4()
    primary = MagicMock()

    mock_q = MagicMock()
    mock_q.first.return_value = primary

    with patch(
        "app.services.subscription_query._build_active_subscriptions_query",
        return_value=mock_q,
    ):
        assert get_primary_active_subscription(db, oid) is primary


def test_get_active_plan_id_returns_plan_or_none():
    sub = MagicMock()
    sub.plan_id = uuid4()

    with patch(
        "app.services.subscription_query.get_primary_active_subscription",
        return_value=sub,
    ):
        assert get_active_plan_id(MagicMock(), uuid4()) == sub.plan_id

    with patch(
        "app.services.subscription_query.get_primary_active_subscription",
        return_value=None,
    ):
        assert get_active_plan_id(MagicMock(), uuid4()) is None


def test_has_active_subscription_truthy_when_first_exists():
    mock_q = MagicMock()
    mock_q.first.return_value = MagicMock()

    with patch(
        "app.services.subscription_query._build_active_subscriptions_query",
        return_value=mock_q,
    ):
        assert has_active_subscription(MagicMock(), uuid4()) is True

    mock_q.first.return_value = None
    with patch(
        "app.services.subscription_query._build_active_subscriptions_query",
        return_value=mock_q,
    ):
        assert has_active_subscription(MagicMock(), uuid4()) is False


def test_count_active_subscriptions():
    mock_q = MagicMock()
    mock_q.count.return_value = 3

    with patch(
        "app.services.subscription_query._build_active_subscriptions_query",
        return_value=mock_q,
    ):
        assert count_active_subscriptions(MagicMock(), uuid4()) == 3


def test_get_subscription_history_orders_and_limits():
    db = MagicMock()
    oid = uuid4()
    rows = [MagicMock()]

    chain = MagicMock()
    chain.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
        rows
    )
    db.query.return_value = chain

    assert get_subscription_history(db, oid, limit=10) == rows

    chain.filter.return_value.order_by.return_value.limit.assert_called_once_with(10)


def test_deprecated_client_aliases_delegate():
    cid = uuid4()
    db = MagicMock()
    subs = [MagicMock()]
    primary = MagicMock()

    with patch(
        "app.services.subscription_query.get_active_subscriptions",
        return_value=subs,
    ) as m1:
        assert get_active_subscriptions_for_client(db, cid) == subs
        m1.assert_called_once_with(db, cid)

    with patch(
        "app.services.subscription_query.get_primary_active_subscription",
        return_value=primary,
    ) as m2:
        assert get_primary_active_subscription_for_client(db, cid) is primary
        m2.assert_called_once_with(db, cid)

    with patch(
        "app.services.subscription_query.has_active_subscription",
        return_value=True,
    ) as m3:
        assert has_active_subscription_for_client(db, cid) is True
        m3.assert_called_once_with(db, cid)

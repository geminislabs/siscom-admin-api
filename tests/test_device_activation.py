"""Tests para app.services.device_activation.activate_device_service."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.device import Device
from app.models.device_service import DeviceService
from app.models.plan import Plan
from app.services.device_activation import activate_device_service


def test_activate_raises_when_device_not_found():
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as ei:
        activate_device_service(session, uuid4(), uuid4(), uuid4(), "MONTHLY")
    assert ei.value.status_code == 404


def test_activate_raises_when_active_service_exists():
    session = MagicMock()
    device = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is Device:
            q.filter.return_value.first.return_value = device
        elif model is DeviceService:
            q.filter.return_value.first.return_value = MagicMock()
        else:
            raise AssertionError(model)
        return q

    session.query.side_effect = query_side_effect

    with pytest.raises(HTTPException) as ei:
        activate_device_service(session, uuid4(), uuid4(), uuid4(), "MONTHLY")
    assert ei.value.status_code == 400


def test_activate_raises_when_plan_missing():
    session = MagicMock()
    device = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        if model is Device:
            q.filter.return_value.first.return_value = device
        elif model is DeviceService:
            q.filter.return_value.first.return_value = None
        elif model is Plan:
            q.filter.return_value.first.return_value = None
        else:
            raise AssertionError(model)
        return q

    session.query.side_effect = query_side_effect

    with pytest.raises(HTTPException) as ei:
        activate_device_service(session, uuid4(), uuid4(), uuid4(), "MONTHLY")
    assert ei.value.status_code == 404


def test_activate_raises_on_invalid_subscription_type():
    session = MagicMock()
    device = MagicMock()
    plan = MagicMock()
    plan.price_monthly = "100"
    plan.price_yearly = "1000"

    def query_side_effect(model):
        q = MagicMock()
        if model is Device:
            q.filter.return_value.first.return_value = device
        elif model is DeviceService:
            q.filter.return_value.first.return_value = None
        elif model is Plan:
            q.filter.return_value.first.return_value = plan
        else:
            raise AssertionError(model)
        return q

    session.query.side_effect = query_side_effect

    with pytest.raises(HTTPException) as ei:
        activate_device_service(session, uuid4(), uuid4(), uuid4(), "WEEKLY")
    assert ei.value.status_code == 400


def test_activate_success_monthly(monkeypatch):
    cid = uuid4()
    dev_pk = uuid4()
    plan_id = uuid4()

    device = MagicMock()
    device.active = False

    plan = MagicMock()
    plan.price_monthly = "299.00"
    plan.price_yearly = "2990.00"

    payment_stub = MagicMock()
    payment_stub.id = uuid4()

    def query_side_effect(model):
        q = MagicMock()
        if model is Device:
            q.filter.return_value.first.return_value = device
        elif model is DeviceService:
            q.filter.return_value.first.return_value = None
        elif model is Plan:
            q.filter.return_value.first.return_value = plan
        else:
            raise AssertionError(model)
        return q

    session = MagicMock()
    session.query.side_effect = query_side_effect

    fixed_exp = datetime(2030, 1, 1)
    monkeypatch.setattr(
        "app.services.device_activation.calculate_expiration",
        lambda st: fixed_exp,
    )

    with patch(
        "app.services.device_activation.Payment",
        return_value=payment_stub,
    ):
        out = activate_device_service(
            session,
            cid,
            dev_pk,
            plan_id,
            "MONTHLY",
            simulate_immediate_payment=True,
        )

    assert isinstance(out, DeviceService)
    assert device.active is True
    session.commit.assert_called_once()

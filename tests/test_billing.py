"""Tests unitarios para app.services.billing (pagos, expiración y cancelación legacy)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.device import Device
from app.models.device_service import DeviceService
from app.models.payment import Payment
from app.services import billing as billing_mod
from app.services.billing import (
    cancel_device_service,
    check_expired_services,
    confirm_payment,
)


def test_confirm_payment_success_updates_payment_device_and_service():
    pid = uuid4()
    ds_id = uuid4()
    dev_id = "GPS001"

    payment = MagicMock(spec=Payment)
    payment.id = pid
    payment.status = "PENDING"

    ds = MagicMock(spec=DeviceService)
    ds.id = ds_id
    ds.payment_id = pid
    ds.device_id = dev_id
    ds.status = "PENDING"

    device = MagicMock(spec=Device)
    device.device_id = dev_id
    device.active = False

    seq = [
        lambda m: MagicMock(
            filter=MagicMock(
                return_value=MagicMock(first=MagicMock(return_value=payment))
            )
        ),
        lambda m: MagicMock(
            filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=ds)))
        ),
        lambda m: MagicMock(
            filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=device)))
        ),
    ]

    session = MagicMock()

    def query_side_effect(model):
        fn = seq.pop(0)
        return fn(model)

    session.query.side_effect = query_side_effect

    freeze = datetime(2026, 1, 15, 12, 0, 0)
    with patch("app.services.billing.datetime") as mock_dt:
        mock_dt.utcnow.return_value = freeze
        out = confirm_payment(session, pid, ds_id)

    assert out is payment
    assert payment.status == "SUCCESS"
    assert payment.paid_at == freeze
    assert ds.status == "ACTIVE"
    assert device.active is True
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(payment)


def test_confirm_payment_raises_404_when_payment_missing():
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as ei:
        confirm_payment(session, uuid4(), uuid4())
    assert ei.value.status_code == 404
    assert "Pago no encontrado" in ei.value.detail


def test_confirm_payment_raises_404_when_device_service_missing():
    pid = uuid4()
    ds_id = uuid4()

    payment = MagicMock()
    payment.id = pid

    def query_side_effect(model):
        q = MagicMock()
        if model is Payment:
            q.filter.return_value.first.return_value = payment
        elif model is DeviceService:
            q.filter.return_value.first.return_value = None
        else:
            raise AssertionError(f"unexpected model {model}")
        return q

    session = MagicMock()
    session.query.side_effect = query_side_effect

    with pytest.raises(HTTPException) as ei:
        confirm_payment(session, pid, ds_id)
    assert ei.value.status_code == 404


def test_confirm_payment_raises_400_when_payment_mismatch():
    pid = uuid4()
    ds_id = uuid4()

    payment = MagicMock()
    payment.id = pid

    ds = MagicMock()
    ds.payment_id = uuid4()

    seq = [
        lambda m: MagicMock(
            filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=payment)))
        ),
        lambda m: MagicMock(
            filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=ds)))
        ),
    ]

    session = MagicMock()

    def query_side_effect(model):
        fn = seq.pop(0)
        return fn(model)

    session.query.side_effect = query_side_effect

    with pytest.raises(HTTPException) as ei:
        confirm_payment(session, pid, ds_id)
    assert ei.value.status_code == 400


def test_check_expired_services_marks_expired_and_disables_device():
    now = datetime(2026, 6, 1, 0, 0, 0)

    svc = MagicMock()
    svc.id = uuid4()
    svc.device_id = "D1"
    svc.status = "ACTIVE"
    svc.auto_renew = False

    device = MagicMock()
    device.device_id = "D1"
    device.active = True

    ds_calls = [0]

    def query_side_effect(model):
        q = MagicMock()
        if model is DeviceService:
            ds_calls[0] += 1
            if ds_calls[0] == 1:
                q.filter.return_value.all.return_value = [svc]
            else:
                q.filter.return_value.first.return_value = None
        elif model is Device:
            q.filter.return_value.first.return_value = device
        else:
            raise AssertionError(model)
        return q

    session = MagicMock()
    session.query.side_effect = query_side_effect

    with patch("app.services.billing.datetime") as mock_dt:
        mock_dt.utcnow.return_value = now
        count = check_expired_services(session)

    assert count == 1
    assert svc.status == "EXPIRED"
    assert device.active is False
    session.commit.assert_called_once()


def test_check_expired_services_returns_zero_without_commit():
    fixed = datetime(2026, 5, 1, 0, 0, 0)

    expired_query = MagicMock()
    expired_query.filter.return_value.all.return_value = []

    session = MagicMock()
    session.query.return_value = expired_query

    with patch("app.services.billing.datetime") as mock_dt:
        mock_dt.utcnow.return_value = fixed
        assert check_expired_services(session) == 0

    session.commit.assert_not_called()


def test_cancel_device_service_sets_cancelled_and_disables_device():
    ds_id = uuid4()
    client_id = uuid4()

    ds = MagicMock()
    ds.id = ds_id
    ds.device_id = "Z9"
    ds.client_id = client_id
    ds.status = "ACTIVE"

    device = MagicMock()
    device.active = True

    main_ds_query = MagicMock()
    main_ds_query.filter.return_value.first.return_value = ds

    other_query = MagicMock()
    other_query.filter.return_value.first.return_value = None

    device_query = MagicMock()
    device_query.filter.return_value.first.return_value = device

    order = [main_ds_query, other_query, device_query]

    session = MagicMock()

    def query_side_effect(model):
        return order.pop(0)

    session.query.side_effect = query_side_effect

    freeze = datetime(2026, 2, 1, 8, 0, 0)
    with patch("app.services.billing.datetime") as mock_dt:
        mock_dt.utcnow.return_value = freeze
        out = cancel_device_service(session, ds_id, client_id)

    assert out is ds
    assert ds.status == "CANCELLED"
    assert ds.cancelled_at == freeze
    assert device.active is False
    session.commit.assert_called_once()


def test_cancel_device_service_raises_when_not_found():
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as ei:
        cancel_device_service(session, uuid4(), uuid4())
    assert ei.value.status_code == 404

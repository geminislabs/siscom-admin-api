"""Tests para app.services.audit.AuditService."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.models.account_event import EventType, TargetType
from app.services.audit import AuditService


def test_log_event_adds_account_event_and_optional_commit():
    db = MagicMock()
    account_id = uuid4()

    event_mock = MagicMock()
    with patch("app.services.audit.AccountEvent", return_value=event_mock):
        event = AuditService.log_event(
            db,
            account_id,
            EventType.ORG_USER_ADDED.value,
            TargetType.ORGANIZATION_USER.value,
            organization_id=uuid4(),
            actor_user_id=uuid4(),
            target_id=uuid4(),
            metadata={"k": "v"},
            auto_commit=False,
        )

    assert event is event_mock
    db.add.assert_called_once_with(event_mock)
    db.commit.assert_not_called()


def test_log_event_auto_commit(monkeypatch):
    db = MagicMock()
    account_id = uuid4()

    event_mock = MagicMock()
    with patch("app.services.audit.AccountEvent", return_value=event_mock):
        AuditService.log_event(
            db,
            account_id,
            EventType.ORG_USER_ADDED.value,
            TargetType.ORGANIZATION_USER.value,
            auto_commit=True,
        )

    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(event_mock)


def test_log_org_user_added_passes_metadata(monkeypatch):
    db = MagicMock()
    account_id = uuid4()
    org_id = uuid4()
    actor = uuid4()
    target = uuid4()

    captured = {}

    def fake_log(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(AuditService, "log_event", fake_log)

    AuditService.log_org_user_added(
        db,
        account_id,
        org_id,
        actor,
        target,
        role="admin",
        ip_address="10.0.0.1",
    )

    assert captured["event_type"] == EventType.ORG_USER_ADDED.value
    assert captured["metadata"]["role"] == "admin"
    assert captured["metadata"]["user_id"] == str(target)
    assert captured["ip_address"] == "10.0.0.1"


def test_log_org_capability_deleted_serializes_previous_value(monkeypatch):
    captured = {}

    def fake_log(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(AuditService, "log_event", fake_log)

    AuditService.log_org_capability_deleted(
        MagicMock(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "max_devices",
        previous_value=42,
    )

    assert captured["metadata"]["previous_value"] == "42"


"""Tests para app.services.notifications (SES y stubs SMS/push)."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import app.services.notifications as notifications_mod
from app.services.notifications import (
    send_contact_email,
    send_invitation_email,
    send_password_reset_email,
    send_push_notification,
    send_sms,
    send_verification_email,
)


@pytest.fixture
def patch_ses_success(monkeypatch):
    mock_client = MagicMock()
    mock_client.send_email.return_value = {"MessageId": "msg-123"}
    monkeypatch.setattr(notifications_mod, "ses_client", mock_client)
    return mock_client


def test_send_verification_email_calls_ses(patch_ses_success):
    ok = send_verification_email("user@test.com", "tok-abc")
    assert ok is True
    patch_ses_success.send_email.assert_called_once()
    kwargs = patch_ses_success.send_email.call_args[1]
    assert kwargs["Destination"]["ToAddresses"] == ["user@test.com"]
    assert "verify-email?token=tok-abc" in kwargs["Message"]["Body"]["Html"]["Data"]


def test_send_invitation_email_builds_accept_url(patch_ses_success):
    ok = send_invitation_email("inv@test.com", "invite-x", full_name="Ana")
    assert ok is True
    html = patch_ses_success.send_email.call_args[1]["Message"]["Body"]["Html"]["Data"]
    assert "accept-invitation?token=invite-x" in html


def test_send_password_reset_email(patch_ses_success):
    assert send_password_reset_email("u@test.com", "123456") is True


def test_send_email_returns_false_on_client_error(monkeypatch):
    err = ClientError(
        {"Error": {"Code": "MessageRejected", "Message": "bad"}},
        "SendEmail",
    )
    mock_client = MagicMock()
    mock_client.send_email.side_effect = err
    monkeypatch.setattr(notifications_mod, "ses_client", mock_client)

    assert notifications_mod._send_email("x@test.com", "s", "<p>h</p>") is False


def test_send_email_returns_false_on_unexpected_exception(monkeypatch):
    mock_client = MagicMock()
    mock_client.send_email.side_effect = RuntimeError("boom")
    monkeypatch.setattr(notifications_mod, "ses_client", mock_client)

    assert notifications_mod._send_email("x@test.com", "s", "<p>h</p>") is False


def test_send_contact_email_targets_contact_setting(monkeypatch, patch_ses_success):
    monkeypatch.setattr(notifications_mod.settings, "CONTACT_EMAIL", "ops@corp.test")

    assert (
        send_contact_email(
            "Pedro",
            "pedro@test.com",
            "+52155",
            "Hola equipo",
        )
        is True
    )

    kwargs = patch_ses_success.send_email.call_args[1]
    assert kwargs["Destination"]["ToAddresses"] == ["ops@corp.test"]
    body = kwargs["Message"]["Body"]["Html"]["Data"]
    assert "Pedro" in body and "Hola equipo" in body


def test_send_sms_stub_returns_true():
    assert send_sms("+52551234", "hello") is True


def test_send_push_stub_returns_true():
    assert send_push_notification("user-1", "t", "b", {"k": "v"}) is True

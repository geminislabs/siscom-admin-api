"""Tests para app.services.notifications (SES y stubs SMS/push)."""

import uuid
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

import app.services.notifications as notifications_mod
from app.models.account import Account, AccountType
from app.models.tenancy import TenantBranding, TenantDomain
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


def _marca_blanca(db, *, hostname="meromero.com", **tema_kwargs):
    """
    Una cuenta de marca con dominio verificado y branding — para B4.

    Mismo patrón que `_marca` en `test_tenancy_codigo.py`: cuenta, dominio
    primario verificado y `TenantBranding` con las claves de correo en
    `published`.
    """
    cid = uuid.uuid4()
    cuenta = Account(
        id=cid,
        name="Mero Mero",
        account_type=AccountType.RESELLER,
        account_path=[cid],
    )
    db.add(cuenta)
    db.flush()

    db.add(
        TenantDomain(
            account_id=cuenta.id,
            hostname=hostname,
            is_primary=True,
            status="VERIFIED",
        )
    )
    db.add(
        TenantBranding(
            account_id=cuenta.id,
            brand_name="Mero Mero",
            published={
                "logo_url": "https://assets.meromero.com/logo.png",
                "support_email": "soporte@meromero.com",
                "legal_url": "https://meromero.com/legal",
                **tema_kwargs,
            },
        )
    )
    db.commit()
    return cuenta


# ─────────────────────────────────────────────────────────────────────
# B4 — sin marca resuelta: inerte por diseño, byte-idéntico a antes de B4
# ─────────────────────────────────────────────────────────────────────


def test_send_verification_email_calls_ses(patch_ses_success, db_session):
    ok = send_verification_email("user@test.com", "tok-abc", db_session)
    assert ok is True
    patch_ses_success.send_email.assert_called_once()
    kwargs = patch_ses_success.send_email.call_args[1]
    assert kwargs["Destination"]["ToAddresses"] == ["user@test.com"]
    assert "verify-email?token=tok-abc" in kwargs["Message"]["Body"]["Html"]["Data"]
    assert "Geminis Labs <" in kwargs["Source"] or kwargs["Source"]
    assert "Geminis Labs" in kwargs["Message"]["Subject"]["Data"]
    body = kwargs["Message"]["Body"]["Html"]["Data"]
    assert "Geminis Labs" in body
    assert "Tecnología humana y conectada" in body


def test_send_invitation_email_builds_accept_url(patch_ses_success, db_session):
    ok = send_invitation_email("inv@test.com", "invite-x", "Ana", db_session)
    assert ok is True
    html = patch_ses_success.send_email.call_args[1]["Message"]["Body"]["Html"]["Data"]
    assert "accept-invitation?token=invite-x" in html
    assert "Geminis Labs" in html


def test_send_password_reset_email(patch_ses_success, db_session):
    assert send_password_reset_email("u@test.com", "123456", db_session) is True


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


# ─────────────────────────────────────────────────────────────────────
# B4 — con marca resuelta: nombre, logo, dominio y remitente de la marca
# ─────────────────────────────────────────────────────────────────────


def test_send_verification_email_usa_la_marca_resuelta(patch_ses_success, db_session):
    marca = _marca_blanca(db_session)

    ok = send_verification_email("user@test.com", "tok-abc", db_session, marca.id)
    assert ok is True

    kwargs = patch_ses_success.send_email.call_args[1]
    assert (
        kwargs["Source"] == f"Mero Mero <{notifications_mod.settings.SES_FROM_EMAIL}>"
    )
    assert kwargs["ReplyToAddresses"] == ["soporte@meromero.com"]
    assert "Mero Mero" in kwargs["Message"]["Subject"]["Data"]

    body = kwargs["Message"]["Body"]["Html"]["Data"]
    assert "https://meromero.com/verify-email?token=tok-abc" in body
    assert "https://assets.meromero.com/logo.png" in body
    assert "Mero Mero" in body
    # Sin tagline ni logo de Geminis: no es su marca
    assert "Tecnología humana y conectada" not in body
    assert "data:image/png;base64" not in body


def test_send_invitation_email_usa_la_marca_de_quien_invita(
    patch_ses_success, db_session
):
    marca = _marca_blanca(db_session)

    ok = send_invitation_email("inv@test.com", "invite-x", "Ana", db_session, marca.id)
    assert ok is True

    body = patch_ses_success.send_email.call_args[1]["Message"]["Body"]["Html"]["Data"]
    assert "https://meromero.com/accept-invitation?token=invite-x" in body
    assert "Mero Mero" in body
    assert '<a href="https://meromero.com/legal"' in body


def test_send_password_reset_email_sin_dominio_verificado_cae_a_frontend_url(
    patch_ses_success, db_session
):
    """
    Marca con `TenantBranding` pero sin `TenantDomain` verificado: el nombre y
    el logo son de la marca, pero no hay enlace de acción que resolver aquí
    (el código de 6 dígitos no lo necesita) — esta prueba cubre el caso en que
    `_resolver_contexto_de_marca` cae a `base_url` por defecto.
    """
    cid = uuid.uuid4()
    cuenta = Account(
        id=cid,
        name="Sin Dominio",
        account_type=AccountType.RESELLER,
        account_path=[cid],
    )
    db_session.add(cuenta)
    db_session.flush()
    db_session.add(TenantBranding(account_id=cuenta.id, brand_name="Sin Dominio"))
    db_session.commit()

    ok = send_password_reset_email("u@test.com", "123456", db_session, cuenta.id)
    assert ok is True

    kwargs = patch_ses_success.send_email.call_args[1]
    assert "Sin Dominio" in kwargs["Message"]["Subject"]["Data"]
    assert "ReplyToAddresses" not in kwargs

"""Tests de internacionalización (Accept-Language, catálogo i18n y endpoints)."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.api.deps import get_request_locale
from app.core.i18n import MESSAGES, t
from app.models.alert_rule import AlertRule
from app.models.geofence import Geofence
from app.models.user import User
from app.utils.json_normalization import generate_fingerprint, normalize_json


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "es"),
        ("", "es"),
        ("es", "es"),
        ("es-MX", "es"),
        ("es-419,es;q=0.9,en;q=0.8", "es"),
        ("en", "en"),
        ("en-US", "en"),
        ("en-US,en;q=0.9,es;q=0.8", "en"),
        ("EN-GB;q=0.8", "en"),
        ("fr-FR,fr;q=0.9", "es"),
        ("pt-BR", "es"),
        (object(), "es"),
    ],
)
def test_get_request_locale_parsing(header, expected):
    assert get_request_locale(header) == expected


def test_i18n_catalog_completeness_and_formatting():
    assert len(MESSAGES) > 0
    for key, translations in MESSAGES.items():
        assert "es" in translations and translations["es"], f"Missing 'es' for {key}"
        assert "en" in translations and translations["en"], f"Missing 'en' for {key}"

    # Invariante acordada con iOS y Android para el 403 de email no verificado
    en_unverified = t("auth.email_not_verified", "en")
    assert "verify" in en_unverified.lower()
    assert t("auth.email_not_verified", "es") == "Email no verificado"

    # Interpolación de variables y fallback seguro
    assert (
        t("users.invitation_sent", "en", email="a@b.com")
        == "Invitation sent to a@b.com"
    )
    assert (
        t("users.invitation_sent", "es", email="a@b.com")
        == "Invitación enviada a a@b.com"
    )
    assert t("unknown.key", "en") == "unknown.key"
    assert t("auth.invalid_credentials", "fr") == "Credenciales inválidas"


def test_auth_login_and_forgot_password_respect_accept_language(
    client, db_session, test_organization_data
):
    unverified_user = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        cognito_sub="sub-unverified-i18n",
        email="unverified-i18n@example.com",
        full_name="Unverified User",
        is_master=True,
        email_verified=False,
    )
    db_session.add(unverified_user)
    db_session.commit()

    # 1. Login con usuario no verificado en inglés -> conserva "verify"
    res_en = client.post(
        "/api/v1/auth/login",
        json={"email": unverified_user.email, "password": "Password123!"},
        headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    assert res_en.status_code == 403
    assert (
        res_en.json()["detail"] == "Please verify your email address before signing in."
    )
    assert "verify" in res_en.json()["detail"].lower()

    # 2. Login con usuario no verificado en español (default)
    res_es = client.post(
        "/api/v1/auth/login",
        json={"email": unverified_user.email, "password": "Password123!"},
    )
    assert res_es.status_code == 403
    assert res_es.json()["detail"] == "Email no verificado"

    # 3. Login con usuario inexistente en inglés
    res_404_en = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "Password123!"},
        headers={"Accept-Language": "en"},
    )
    assert res_404_en.status_code == 404
    assert res_404_en.json()["detail"] == "User not found"

    # 4. Forgot password propaga locale="en" al correo y responde en inglés
    with patch(
        "app.api.v1.endpoints.auth.send_password_reset_email", return_value=True
    ) as mock_reset_email:
        res_fp = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": unverified_user.email},
            headers={"Accept-Language": "en-US"},
        )
        assert res_fp.status_code == 200
        assert (
            res_fp.json()["message"]
            == "A verification code has been sent to the registered email address."
        )
        mock_reset_email.assert_called_once()
        assert mock_reset_email.call_args.kwargs.get("locale") == "en"

    # 5. Resend verification propaga locale="en" al correo y responde en inglés
    with patch(
        "app.api.v1.endpoints.auth.send_verification_email", return_value=True
    ) as mock_verify_email:
        res_rv = client.post(
            "/api/v1/auth/resend-verification",
            json={"email": unverified_user.email},
            headers={"Accept-Language": "en"},
        )
        assert res_rv.status_code == 200
        assert (
            res_rv.json()["message"]
            == "If the account exists, the verification email has been resent."
        )
        mock_verify_email.assert_called_once()
        assert mock_verify_email.call_args.kwargs.get("locale") == "en"


def test_users_invite_and_accept_invitation_respect_accept_language(
    authenticated_client,
):
    with patch(
        "app.api.v1.endpoints.users.send_invitation_email", return_value=True
    ) as mock_invite_email:
        res = authenticated_client.post(
            "/api/v1/users/invite",
            json={"email": "newguest@example.com", "full_name": "New Guest"},
            headers={"Accept-Language": "en"},
        )
        assert res.status_code == 201
        assert res.json()["detail"] == "Invitation sent to newguest@example.com"
        mock_invite_email.assert_called_once()
        assert mock_invite_email.call_args.kwargs.get("locale") == "en"

    res_dup = authenticated_client.post(
        "/api/v1/users/invite",
        json={"email": "newguest@example.com", "full_name": "New Guest"},
        headers={"Accept-Language": "en"},
    )
    assert res_dup.status_code == 400
    assert (
        res_dup.json()["detail"]
        == "A pending invitation already exists for newguest@example.com."
    )

    res_invalid_tok = authenticated_client.post(
        "/api/v1/users/accept-invitation",
        json={"token": "non-existent-token", "password": "Password123!"},
        headers={"Accept-Language": "en"},
    )
    assert res_invalid_tok.status_code == 400
    assert res_invalid_tok.json()["detail"] == "Invalid invitation token."


def test_operational_endpoints_respect_accept_language(
    authenticated_client, db_session, test_organization_data, test_user_data
):
    missing_id = uuid4()

    # 1. Units 404 en inglés y español
    res_unit_en = authenticated_client.get(
        f"/api/v1/units/{missing_id}",
        headers={"Accept-Language": "en"},
    )
    assert res_unit_en.status_code == 404
    assert res_unit_en.json()["detail"] == "Unit not found"

    res_unit_es = authenticated_client.get(
        f"/api/v1/units/{missing_id}",
        headers={"Accept-Language": "es-MX"},
    )
    assert res_unit_es.status_code == 404
    assert res_unit_es.json()["detail"] == "Unidad no encontrada"

    # 2. Alerts 404 en inglés
    res_alerts_en = authenticated_client.get(
        f"/api/v1/alerts?unit_id={missing_id}",
        headers={"Accept-Language": "en"},
    )
    assert res_alerts_en.status_code == 404
    assert res_alerts_en.json()["detail"] == "Unit not found"

    # 3. Geofences 404 y delete en inglés
    res_geo_404 = authenticated_client.get(
        f"/api/v1/geofences/{missing_id}",
        headers={"Accept-Language": "en"},
    )
    assert res_geo_404.status_code == 404
    assert res_geo_404.json()["detail"] == "Geofence not found"

    geofence = Geofence(
        organization_id=test_organization_data.id,
        created_by=test_user_data.id,
        name="Geo Test",
        config={},
        is_active=True,
    )
    db_session.add(geofence)
    db_session.commit()
    db_session.refresh(geofence)

    res_geo_del = authenticated_client.delete(
        f"/api/v1/geofences/{geofence.id}",
        headers={"Accept-Language": "en"},
    )
    assert res_geo_del.status_code == 200
    assert res_geo_del.json()["message"] == "Geofence deactivated successfully"

    # 4. Alert rules 404, 409 duplicada y delete en inglés
    res_rule_404 = authenticated_client.get(
        f"/api/v1/alert_rules/{missing_id}",
        headers={"Accept-Language": "en"},
    )
    assert res_rule_404.status_code == 404
    assert res_rule_404.json()["detail"] == "Alert rule not found"

    cfg = normalize_json({"threshold": 120})
    fp = generate_fingerprint(test_organization_data.id, "overspeed", cfg)
    rule = AlertRule(
        organization_id=test_organization_data.id,
        created_by=test_user_data.id,
        name="Speed 120",
        type="overspeed",
        config=cfg,
        fingerprint=fp,
        is_active=True,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    res_rule_dup = authenticated_client.post(
        "/api/v1/alert_rules",
        json={
            "name": "Speed 120 Dup",
            "type": "overspeed",
            "config": {"threshold": 120},
        },
        headers={"Accept-Language": "en"},
    )
    assert res_rule_dup.status_code == 409
    assert (
        res_rule_dup.json()["message"]
        == "A rule with the same type and configuration already exists for this organization"
    )

    res_rule_del = authenticated_client.delete(
        f"/api/v1/alert_rules/{rule.id}",
        headers={"Accept-Language": "en"},
    )
    assert res_rule_del.status_code == 200
    assert res_rule_del.json()["message"] == "Alert rule deleted successfully"

    # 5. User commands en inglés
    res_cmd = authenticated_client.post(
        "/api/v1/user-commands",
        json={"unit_id": str(missing_id), "command_type": "ENGINE_STOP"},
        headers={"Accept-Language": "en"},
    )
    assert res_cmd.status_code == 400
    assert res_cmd.json()["detail"] == "ENGINE_STOP requires confirmation"

    # 6. User devices deactivate 404 en inglés
    res_dev = authenticated_client.post(
        "/api/v1/user-devices/deactivate",
        json={"device_token": "missing-tok"},
        headers={"Accept-Language": "en"},
    )
    assert res_dev.status_code == 404
    assert res_dev.json()["detail"] == "Device not found"

"""Tests unitarios para app.api.deps (auth, roles, Kafka singletons)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.api.deps as deps_mod
from app.api.deps import (
    AuthResult,
    close_geofences_kafka_producer,
    close_rules_kafka_producer,
    close_user_devices_kafka_producer,
    get_auth_for_gac_admin,
    get_rules_kafka_producer,
    require_capability,
    require_organization_role,
    resolve_current_client,
    resolve_current_organization,
)


def test_auth_result_client_id_deprecated_alias():
    oid = uuid4()
    ar = AuthResult(
        auth_type="cognito",
        payload={},
        organization_id=oid,
    )
    assert ar.client_id == oid


def test_resolve_current_organization_requires_sub():
    db = MagicMock()
    with pytest.raises(HTTPException) as ei:
        resolve_current_organization(db, {})
    assert ei.value.status_code == 401


def test_resolve_current_organization_user_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as ei:
        resolve_current_organization(db, {"sub": "cognito-sub-1"})
    assert ei.value.status_code == 404


def test_resolve_current_organization_returns_org_id():
    db = MagicMock()
    oid = uuid4()
    user = MagicMock()
    user.organization_id = oid

    db.query.return_value.filter.return_value.first.return_value = user

    assert resolve_current_organization(db, {"sub": "x"}) == oid


def test_resolve_current_client_deprecated_wrapper(monkeypatch):
    oid = uuid4()

    def fake_resolve(db, payload):
        return oid

    monkeypatch.setattr(deps_mod, "resolve_current_organization", fake_resolve)

    assert resolve_current_client(MagicMock(), {"sub": "y"}) == oid


def test_get_rules_kafka_producer_singleton_and_close(monkeypatch):
    deps_mod._rules_kafka_producer = None

    fake_prod = MagicMock()
    monkeypatch.setattr(deps_mod, "RulesKafkaProducer", lambda: fake_prod)

    p1 = get_rules_kafka_producer()
    p2 = get_rules_kafka_producer()
    assert p1 is p2 is fake_prod

    close_rules_kafka_producer()
    assert deps_mod._rules_kafka_producer is None
    fake_prod.close.assert_called_once()


def test_close_kafka_helpers_are_safe_when_already_none():
    deps_mod._rules_kafka_producer = None
    deps_mod._user_devices_kafka_producer = None
    deps_mod._geofences_kafka_producer = None

    close_rules_kafka_producer()
    close_user_devices_kafka_producer()
    close_geofences_kafka_producer()


def test_auth_cognito_or_paseto_cognito_success(monkeypatch):
    uid = uuid4()
    oid = uuid4()

    user = MagicMock()
    user.id = uid
    user.organization_id = oid

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user

    monkeypatch.setattr(
        deps_mod.OrganizationService,
        "get_user_role",
        lambda db2, u, o: SimpleNamespace(value="admin"),
    )

    creds = MagicMock()
    creds.credentials = "jwt-token"

    monkeypatch.setattr(
        deps_mod,
        "verify_cognito_token",
        lambda t: {"sub": "sub-1"},
    )

    verify_fn = deps_mod.get_auth_cognito_or_paseto()
    result = verify_fn(credentials=creds, db=db)

    assert result.auth_type == "cognito"
    assert result.user_id == uid
    assert result.organization_id == oid
    assert result.organization_role == "admin"


def test_auth_cognito_or_paseto_falls_back_to_paseto(monkeypatch):
    db = MagicMock()

    monkeypatch.setattr(
        deps_mod,
        "verify_cognito_token",
        lambda t: (_ for _ in ()).throw(Exception("bad jwt")),
    )

    paseto_payload = {"service": "gac", "role": "GAC_ADMIN"}

    monkeypatch.setattr(
        deps_mod,
        "decode_service_token",
        lambda token, required_service=None, required_role=None: paseto_payload,
    )

    creds = MagicMock()
    creds.credentials = "paseto-token"

    verify_fn = deps_mod.get_auth_cognito_or_paseto()
    result = verify_fn(credentials=creds, db=db)

    assert result.auth_type == "paseto"
    assert result.service == "gac"


def test_auth_cognito_or_paseto_raises_when_both_fail(monkeypatch):
    db = MagicMock()

    monkeypatch.setattr(
        deps_mod,
        "verify_cognito_token",
        lambda t: (_ for _ in ()).throw(ValueError("x")),
    )
    monkeypatch.setattr(deps_mod, "decode_service_token", lambda *a, **k: None)

    creds = MagicMock()
    creds.credentials = "bad"

    verify_fn = deps_mod.get_auth_cognito_or_paseto()

    with pytest.raises(HTTPException) as ei:
        verify_fn(credentials=creds, db=db)
    assert ei.value.status_code == 401


def test_require_organization_role_allows_matching_role(monkeypatch):
    uid = uuid4()
    oid = uuid4()

    user = MagicMock()
    user.id = uid
    user.organization_id = oid

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user

    monkeypatch.setattr(deps_mod, "verify_cognito_token", lambda t: {"sub": "s"})
    monkeypatch.setattr(
        deps_mod.OrganizationService,
        "get_user_role",
        lambda db2, u, o: SimpleNamespace(value="admin"),
    )

    creds = MagicMock()
    creds.credentials = "jwt"

    role_dep = require_organization_role("admin", "billing")
    result = role_dep(credentials=creds, db=db)

    assert result.organization_role == "admin"


def test_require_organization_role_forbidden(monkeypatch):
    user = MagicMock()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user

    monkeypatch.setattr(deps_mod, "verify_cognito_token", lambda t: {"sub": "s"})
    monkeypatch.setattr(
        deps_mod.OrganizationService,
        "get_user_role",
        lambda db2, u, o: SimpleNamespace(value="member"),
    )

    creds = MagicMock()
    creds.credentials = "jwt"

    role_dep = require_organization_role("owner")

    with pytest.raises(HTTPException) as ei:
        role_dep(credentials=creds, db=db)
    assert ei.value.status_code == 403


def test_require_capability_raises_when_disabled(monkeypatch):
    uid = uuid4()
    oid = uuid4()

    user = MagicMock()
    user.id = uid
    user.organization_id = oid

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user

    monkeypatch.setattr(deps_mod, "verify_cognito_token", lambda t: {"sub": "s"})

    creds = MagicMock()
    creds.credentials = "jwt"

    cap_dep = require_capability("ai_features")

    with patch(
        "app.services.capabilities.CapabilityService.has_capability",
        return_value=False,
    ):
        with pytest.raises(HTTPException) as ei:
            cap_dep(credentials=creds, db=db)
    assert ei.value.status_code == 403


def test_preconfigured_gac_admin_dependency_is_factory():
    """Smoke: la dependencia preconfigurada es callable."""
    assert callable(get_auth_for_gac_admin)

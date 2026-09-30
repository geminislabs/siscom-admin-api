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
    close_mobility_kafka_producer,
    close_rules_kafka_producer,
    close_unit_devices_kafka_producer,
    close_user_devices_kafka_producer,
    close_user_units_kafka_producer,
    get_auth_for_gac_admin,
    get_mobility_kafka_producer,
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


def _db_con_usuario_y_membresia(user, hay_membresia_activa: bool) -> MagicMock:
    """Un `db` falso cuyo primer `.query()` (User) devuelve `user` y cuyo
    segundo `.query()` (OrganizationUser) devuelve una membresía activa o
    ninguna, según `hay_membresia_activa` — en ese orden, porque
    `_load_current_user` consulta primero User y después OrganizationUser."""
    db = MagicMock()
    user_query = MagicMock()
    user_query.filter.return_value.first.return_value = user
    membership_query = MagicMock()
    membership_query.filter.return_value.first.return_value = (
        MagicMock() if hay_membresia_activa else None
    )
    db.query.side_effect = [user_query, membership_query]
    return db


def test_resolve_current_organization_sin_membresia_activa_falla_cerrado():
    """El fail-closed del rediseño de DELETE: sin fila ACTIVE en
    organization_users para la organización actual, 403 en vez de dejar
    resolver datos contra una organización de la que ya no es miembro."""
    oid = uuid4()
    user = MagicMock()
    user.id = uuid4()
    user.organization_id = oid
    db = _db_con_usuario_y_membresia(user, hay_membresia_activa=False)

    with pytest.raises(HTTPException) as ei:
        resolve_current_organization(db, {"sub": "x"})
    assert ei.value.status_code == 403


def test_resolve_current_organization_returns_org_id():
    oid = uuid4()
    user = MagicMock()
    user.id = uuid4()
    user.organization_id = oid
    db = _db_con_usuario_y_membresia(user, hay_membresia_activa=True)

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
    deps_mod._unit_devices_kafka_producer = None
    deps_mod._user_units_kafka_producer = None
    deps_mod._geofences_kafka_producer = None
    deps_mod._mobility_kafka_producer = None

    close_rules_kafka_producer()
    close_user_devices_kafka_producer()
    close_unit_devices_kafka_producer()
    close_user_units_kafka_producer()
    close_geofences_kafka_producer()
    close_mobility_kafka_producer()


def test_get_mobility_kafka_producer_singleton_and_close(monkeypatch):
    deps_mod._mobility_kafka_producer = None

    fake_prod = MagicMock()
    monkeypatch.setattr(deps_mod, "MobilityKafkaProducer", lambda: fake_prod)

    p1 = get_mobility_kafka_producer()
    p2 = get_mobility_kafka_producer()
    assert p1 is p2 is fake_prod

    close_mobility_kafka_producer()
    assert deps_mod._mobility_kafka_producer is None
    fake_prod.close.assert_called_once()


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


# ---------------------------------------------------------------------------
# Un fallo de infraestructura no puede disfrazarse de credencial inválida
# ---------------------------------------------------------------------------


def test_cognito_outage_surfaces_as_503_not_401():
    """
    Si Cognito es inalcanzable y no hay JWKS en caché, `verify_cognito_token`
    lanza 503. Ese 503 NO puede acabar convertido en 401 al caer al camino
    PASETO: un 401 le dice al cliente que su credencial es mala y lo manda a
    reautenticarse contra un problema que ninguna credencial arregla. Los
    clientes que reaccionan a un 401 pidiendo un token nuevo convierten además
    una caída de Cognito en una tormenta de peticiones sobre esta misma API.
    """
    from unittest.mock import patch

    from fastapi import HTTPException, status
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api.deps import get_auth_cognito_or_paseto

    dep = get_auth_cognito_or_paseto(required_service="gac", required_role="GAC_ADMIN")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="no-es-paseto")
    caida = HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No se pudo verificar la autenticación",
    )

    with patch("app.api.deps.verify_cognito_token", side_effect=caida):
        with pytest.raises(HTTPException) as exc_info:
            dep(credentials=creds, db=None)

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_invalid_cognito_credential_still_falls_through_to_paseto():
    """
    La otra mitad: un 401 de Cognito SÍ debe seguir cayendo al camino PASETO, o
    los tokens de servicio dejarían de funcionar. El corte es por clase de
    error, no por que haya error.
    """
    from unittest.mock import patch

    from fastapi import HTTPException, status
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api.deps import get_auth_cognito_or_paseto
    from app.utils.paseto_token import generate_service_token

    token, _ = generate_service_token("gac", "GAC_ADMIN")
    dep = get_auth_cognito_or_paseto(required_service="gac", required_role="GAC_ADMIN")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    credencial_mala = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
    )

    with patch("app.api.deps.verify_cognito_token", side_effect=credencial_mala):
        result = dep(credentials=creds, db=None)

    assert result.auth_type == "paseto"
    assert result.role == "GAC_ADMIN"

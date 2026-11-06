"""
Tests de la emisión de data tokens de extremo a extremo.

Cubren el orquestador (`issue_for_subject`) y el endpoint. Valkey se sustituye
por un doble; la firma es real.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pyseto
import pytest
from fastapi import status
from pyseto import Key

from app.api.deps import get_data_token_issuer, get_scope_store
from app.main import app
from app.models.device import Device
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.models.user_unit import UserUnit
from app.services.access_control import ScopeSubject
from app.services.data_token_issuance import issue_for_subject
from app.services.scope_store import ScopeStore, jti_key, owner_key, scope_keys
from app.utils.data_token import DataTokenIssuer, generate_ed25519_keypair_b64
from tests.test_scope_store import FakeValkey

INDEX_SECRET = base64.b64encode(b"issuance-secret-exactly-32-bytes").decode()


@pytest.fixture
def keypair():
    return generate_ed25519_keypair_b64()


@pytest.fixture
def issuer(monkeypatch, keypair):
    monkeypatch.setattr(
        "app.utils.data_token.settings.DATA_TOKEN_PRIVATE_KEY_B64", keypair[0]
    )
    return DataTokenIssuer()


@pytest.fixture
def fake_valkey():
    return FakeValkey()


@pytest.fixture
def store(monkeypatch, fake_valkey):
    monkeypatch.setattr(
        "app.services.scope_store.settings.DATA_TOKEN_INDEX_SECRET_B64", INDEX_SECRET
    )
    return ScopeStore(fake_valkey)


@pytest.fixture
def fleet(db_session, test_organization_data, test_user_data):
    """Dos unidades con dispositivo; el usuario tiene concedida solo la primera."""
    units, devices = [], []
    for i in (1, 2):
        unit = Unit(id=uuid4(), organization_id=test_organization_data.id, name=f"U{i}")
        device = Device(device_id=f"{i}" * 15, status="asignado")
        db_session.add_all([unit, device])
        db_session.flush()
        db_session.add(UnitDevice(unit_id=unit.id, device_id=device.device_id))
        units.append(unit)
        devices.append(device)

    db_session.add(UserUnit(user_id=test_user_data.id, unit_id=units[0].id))
    db_session.commit()
    for obj in units + devices:
        db_session.refresh(obj)
    return {"units": units, "devices": devices, "org_id": test_organization_data.id}


def _payload(public_pem, token):
    verifier = Key.new(version=4, purpose="public", key=public_pem.encode("ascii"))
    return json.loads(pyseto.decode(keys=verifier, token=token).payload)


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------


def test_scope_is_indexed_by_opaque_ref(
    db_session, fleet, issuer, store, fake_valkey, keypair
):
    """
    Las **claves** del hash son los refs opacos: es lo único que el cliente
    conoce y lo único con lo que puede preguntar.
    """
    issued = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=uuid4(),
        issuer=issuer,
        store=store,
    )

    dev_key, unit_key = scope_keys(issued.scope_ref)
    assert set(fake_valkey.hashes[dev_key]) == {
        str(d.device_ref) for d in fleet["devices"]
    }
    assert set(fake_valkey.hashes[unit_key]) == {
        str(u.unit_ref) for u in fleet["units"]
    }


def test_scope_translates_each_ref_to_its_internal_id(
    db_session, fleet, issuer, store, fake_valkey
):
    """
    El **valor** es el identificador interno, para que siscom-api autorice y
    traduzca en un solo `HGET` sin llamar aquí en el camino caliente.
    """
    issued = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=uuid4(),
        issuer=issuer,
        store=store,
    )

    dev_key, unit_key = scope_keys(issued.scope_ref)
    for device in fleet["devices"]:
        value = json.loads(fake_valkey.hget(dev_key, str(device.device_ref)))
        assert value["id"] == device.device_id
    for unit in fleet["units"]:
        value = json.loads(fake_valkey.hget(unit_key, str(unit.unit_ref)))
        assert value["id"] == str(unit.id)


def test_an_unlisted_ref_is_denied(db_session, fleet, issuer, store, fake_valkey):
    """`nil` es la denegación: no hay subconjunto ni respuesta parcial."""
    issued = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=uuid4(),
        issuer=issuer,
        store=store,
    )
    dev_key, _ = scope_keys(issued.scope_ref)
    assert fake_valkey.hget(dev_key, str(uuid4())) is None


def test_user_scope_is_narrower_than_organization_scope(
    db_session, fleet, issuer, store, fake_valkey, test_user_data
):
    issued = issue_for_subject(
        db_session,
        subject=ScopeSubject(
            organization_id=fleet["org_id"], user_id=test_user_data.id
        ),
        subject_id=test_user_data.id,
        issuer=issuer,
        store=store,
    )
    dev_key, _ = scope_keys(issued.scope_ref)
    assert set(fake_valkey.hashes[dev_key]) == {str(fleet["devices"][0].device_ref)}


def test_token_only_carries_the_scope_ref(db_session, fleet, issuer, store, keypair):
    issued = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=uuid4(),
        issuer=issuer,
        store=store,
    )
    payload = _payload(keypair[1], issued.token)
    assert set(payload) == {"jti", "scope_ref", "aud", "iat", "nbf", "exp"}
    assert UUID(payload["scope_ref"]) == issued.scope_ref


def test_issuing_again_keeps_the_previous_scope(
    db_session, fleet, issuer, store, fake_valkey
):
    """
    D1: emitir no revoca. Dos clientes del mismo usuario renuevan a la vez sin
    matarse entre sí; estrechar permisos lo cubre
    `app/services/session_revocation.py` (ver `tests/test_session_revocation.py`).
    """
    subject_id = uuid4()
    first = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=subject_id,
        issuer=issuer,
        store=store,
    )
    assert scope_keys(first.scope_ref)[0] in fake_valkey.hashes

    second = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=subject_id,
        issuer=issuer,
        store=store,
    )

    assert second.scope_ref != first.scope_ref
    assert scope_keys(first.scope_ref)[0] in fake_valkey.hashes
    assert scope_keys(second.scope_ref)[0] in fake_valkey.hashes


def test_issuing_does_not_revoke_another_subject(
    db_session, fleet, issuer, store, fake_valkey
):
    other = uuid4()
    theirs = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=other,
        issuer=issuer,
        store=store,
    )
    issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=uuid4(),
        issuer=issuer,
        store=store,
    )
    assert scope_keys(theirs.scope_ref)[0] in fake_valkey.hashes


def test_expiry_respects_the_configured_ceiling(db_session, fleet, issuer, store):
    now = datetime.now(timezone.utc)
    issued = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=uuid4(),
        issuer=issuer,
        store=store,
        now=now,
    )
    assert issued.expires_at == now + timedelta(seconds=600)


def test_a_closing_scope_boundary_shortens_the_token(
    monkeypatch, db_session, fleet, issuer, store
):
    """El gancho de las ventanas de team ya está cableado aunque aún devuelva None."""
    now = datetime.now(timezone.utc)
    boundary = now + timedelta(minutes=2)
    monkeypatch.setattr(
        "app.services.data_token_issuance.next_scope_boundary",
        lambda db, subject: boundary,
    )
    issued = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=uuid4(),
        issuer=issuer,
        store=store,
        now=now,
    )
    assert issued.expires_at == boundary


def test_a_subject_with_nothing_gets_an_empty_but_valid_scope(
    db_session, issuer, store, keypair
):
    issued = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=uuid4()),
        subject_id=uuid4(),
        issuer=issuer,
        store=store,
    )
    assert _payload(keypair[1], issued.token)["scope_ref"] == str(issued.scope_ref)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def test_endpoint_returns_a_usable_token(
    authenticated_client, fleet, issuer, store, keypair
):
    app.dependency_overrides[get_data_token_issuer] = lambda: issuer
    app.dependency_overrides[get_scope_store] = lambda: store

    response = authenticated_client.post("/api/v1/auth/data-token")
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 600
    assert _payload(keypair[1], body["token"])["aud"] == "siscom-api"


def test_endpoint_response_does_not_leak_the_scope(
    authenticated_client, fleet, issuer, store
):
    """Devolver el alcance crearía una segunda copia que puede desincronizarse."""
    app.dependency_overrides[get_data_token_issuer] = lambda: issuer
    app.dependency_overrides[get_scope_store] = lambda: store

    body = authenticated_client.post("/api/v1/auth/data-token").json()
    assert set(body) == {"token", "expires_at", "expires_in", "token_type"}


def test_endpoint_requires_authentication(client):
    assert client.post("/api/v1/auth/data-token").status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


def test_endpoint_returns_503_without_signing_key(
    monkeypatch, authenticated_client, store
):
    monkeypatch.setattr(
        "app.utils.data_token.settings.DATA_TOKEN_PRIVATE_KEY_B64", None
    )
    app.dependency_overrides[get_data_token_issuer] = lambda: DataTokenIssuer()
    app.dependency_overrides[get_scope_store] = lambda: store

    response = authenticated_client.post("/api/v1/auth/data-token")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_endpoint_returns_503_without_valkey(authenticated_client, issuer):
    app.dependency_overrides[get_data_token_issuer] = lambda: issuer
    app.dependency_overrides[get_scope_store] = lambda: ScopeStore(None)

    response = authenticated_client.post("/api/v1/auth/data-token")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_endpoint_returns_503_without_revocation_secret(
    monkeypatch, authenticated_client, issuer, fake_valkey
):
    """No se emiten credenciales que no se puedan revocar."""
    monkeypatch.setattr(
        "app.services.scope_store.settings.DATA_TOKEN_INDEX_SECRET_B64", None
    )
    app.dependency_overrides[get_data_token_issuer] = lambda: issuer
    app.dependency_overrides[get_scope_store] = lambda: ScopeStore(fake_valkey)

    response = authenticated_client.post("/api/v1/auth/data-token")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# Cruce forense: el `jti` guardado tiene que ser el firmado
# ---------------------------------------------------------------------------


def test_the_recorded_jti_is_the_one_inside_the_token(
    db_session, fleet, issuer, store, fake_valkey, keypair
):
    """
    Si el `jti` que se guarda no fuese el que va firmado, el cruce con los logs
    de siscom-api no reconstruiría nada. Es la propiedad de la que depende toda
    la trazabilidad del plano de datos.
    """
    subject_id = uuid4()
    issued = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=subject_id,
        issuer=issuer,
        store=store,
    )

    signed_jti = UUID(_payload(keypair[1], issued.token)["jti"])

    assert signed_jti == issued.jti
    assert jti_key(signed_jti) in fake_valkey.strings
    assert fake_valkey.strings[jti_key(signed_jti)] == owner_key(subject_id)


def test_the_trail_does_not_reveal_the_subject(
    db_session, fleet, issuer, store, fake_valkey
):
    subject_id = uuid4()
    issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=subject_id,
        issuer=issuer,
        store=store,
    )
    everything = json.dumps(
        {
            "sets": {k: sorted(v) for k, v in fake_valkey.sets.items()},
            "hashes": fake_valkey.hashes,
            "strings": fake_valkey.strings,
        }
    )
    assert str(subject_id) not in everything


def test_each_issuance_leaves_its_own_trail(
    db_session, fleet, issuer, store, fake_valkey
):
    """Revocar el alcance anterior no borra su rastro: sigue siendo investigable."""
    subject_id = uuid4()
    first = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=subject_id,
        issuer=issuer,
        store=store,
    )
    second = issue_for_subject(
        db_session,
        subject=ScopeSubject(organization_id=fleet["org_id"]),
        subject_id=subject_id,
        issuer=issuer,
        store=store,
    )

    assert first.jti != second.jti
    assert jti_key(first.jti) in fake_valkey.strings
    assert jti_key(second.jti) in fake_valkey.strings


# ---------------------------------------------------------------------------
# Compartir ubicación sobre el data token
# ---------------------------------------------------------------------------


def test_share_token_scope_is_a_single_device(fleet, issuer, store, fake_valkey):
    from app.services.data_token_issuance import issue_share_token

    unit, device = fleet["units"][0], fleet["devices"][0]
    issued = issue_share_token(
        unit_ref=unit.unit_ref,
        unit_id=unit.id,
        device_ref=device.device_ref,
        device_id=device.device_id,
        issuer=issuer,
        store=store,
    )

    dev_key, _ = scope_keys(issued.scope_ref)
    assert set(fake_valkey.hashes[dev_key]) == {str(device.device_ref)}
    assert fake_valkey.hget(dev_key, str(fleet["devices"][1].device_ref)) is None
    # Un enlace compartido es sobre lo que pasa ahora: ventana abierta
    assert json.loads(fake_valkey.hget(dev_key, str(device.device_ref)))["windows"] == [
        {"from": None, "to": None}
    ]


def test_sharing_can_be_stopped(fleet, issuer, store, fake_valkey):
    """
    Lo que el formato v4.local no permitía: un enlace emitido vivía sus treinta
    minutos y no había forma de apagarlo.
    """
    from app.services.data_token_issuance import (
        issue_share_token,
        revoke_shares_for_unit,
    )

    unit, device = fleet["units"][0], fleet["devices"][0]
    issued = issue_share_token(
        unit_ref=unit.unit_ref,
        unit_id=unit.id,
        device_ref=device.device_ref,
        device_id=device.device_id,
        issuer=issuer,
        store=store,
    )
    dev_key, _ = scope_keys(issued.scope_ref)
    assert fake_valkey.hget(dev_key, str(device.device_ref)) is not None

    assert revoke_shares_for_unit(store, unit.id) == 1
    assert fake_valkey.hget(dev_key, str(device.device_ref)) is None


def test_stopping_one_unit_does_not_touch_another(fleet, issuer, store, fake_valkey):
    from app.services.data_token_issuance import (
        issue_share_token,
        revoke_shares_for_unit,
    )

    issued = []
    for unit, device in zip(fleet["units"], fleet["devices"], strict=True):
        issued.append(
            issue_share_token(
                unit_ref=unit.unit_ref,
                unit_id=unit.id,
                device_ref=device.device_ref,
                device_id=device.device_id,
                issuer=issuer,
                store=store,
            )
        )

    revoke_shares_for_unit(store, fleet["units"][0].id)

    assert scope_keys(issued[0].scope_ref)[0] not in fake_valkey.hashes
    assert scope_keys(issued[1].scope_ref)[0] in fake_valkey.hashes


def test_a_share_survives_the_owner_renewing_their_session(
    db_session, fleet, issuer, store, fake_valkey, test_user_data
):
    """
    El choque que motivó separar los índices por propósito: compartir es un acto
    deliberado y no debe apagarse porque el usuario refresque su sesión.
    """
    from app.services.data_token_issuance import issue_share_token

    unit, device = fleet["units"][0], fleet["devices"][0]
    share = issue_share_token(
        unit_ref=unit.unit_ref,
        unit_id=unit.id,
        device_ref=device.device_ref,
        device_id=device.device_id,
        issuer=issuer,
        store=store,
    )

    for _ in range(2):
        issue_for_subject(
            db_session,
            subject=ScopeSubject(organization_id=fleet["org_id"]),
            subject_id=test_user_data.id,
            issuer=issuer,
            store=store,
        )

    assert scope_keys(share.scope_ref)[0] in fake_valkey.hashes


def test_share_token_lives_longer_than_a_session_token(fleet, issuer, store):
    from app.services.data_token_issuance import issue_share_token

    unit, device = fleet["units"][0], fleet["devices"][0]
    now = datetime.now(timezone.utc)
    issued = issue_share_token(
        unit_ref=unit.unit_ref,
        unit_id=unit.id,
        device_ref=device.device_ref,
        device_id=device.device_id,
        issuer=issuer,
        store=store,
        now=now,
    )
    assert issued.expires_at == now + timedelta(seconds=1800)


# ---------------------------------------------------------------------------
# Revocación best effort: nunca tumba la operación que la provocó
# ---------------------------------------------------------------------------


def test_revocation_failure_does_not_propagate(monkeypatch, fake_valkey):
    """
    Desasignar una unidad ya ha surtido efecto en Postgres cuando llegamos a
    revocar. Un Valkey caído no puede convertir eso en un error para el usuario.
    """
    from app.services.data_token_issuance import revoke_sessions_for_user

    monkeypatch.setattr(
        "app.services.scope_store.settings.DATA_TOKEN_INDEX_SECRET_B64", None
    )
    assert revoke_sessions_for_user(ScopeStore(fake_valkey), uuid4()) == 0


def test_revocation_without_valkey_does_not_propagate():
    from app.services.data_token_issuance import revoke_sessions_for_user

    assert revoke_sessions_for_user(ScopeStore(None), uuid4()) == 0


def test_share_token_carries_no_device_identifier(fleet, issuer, store, keypair):
    """
    Un enlace compartido es público por definición: cualquiera que lo tenga puede
    leer la carga útil, porque en v4.public va firmada pero en claro. El formato
    anterior metía ahí el `device_id` —el IMEI— y el `unit_id`.
    """
    from app.services.data_token_issuance import issue_share_token

    unit, device = fleet["units"][0], fleet["devices"][0]
    issued = issue_share_token(
        unit_ref=unit.unit_ref,
        unit_id=unit.id,
        device_ref=device.device_ref,
        device_id=device.device_id,
        issuer=issuer,
        store=store,
    )

    payload = _payload(keypair[1], issued.token)
    assert set(payload) == {"jti", "scope_ref", "aud", "iat", "nbf", "exp"}

    raw = json.dumps(payload)
    assert device.device_id not in raw
    assert str(device.device_ref) not in raw
    assert str(unit.id) not in raw
    assert str(unit.unit_ref) not in raw

"""Revocación de data tokens de sesión desde el ORM (D1).

Como en `test_control_plane_eventos.py`, casi todo se escribe con la sesión
directamente: lo que se afirma es que **cualquier** escritura que estrecha el
alcance revoca, venga del endpoint que venga. Lo que ensancha no revoca.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_current_user
from app.main import app as fastapi_app
from app.models.device import Device
from app.models.organization_user import (
    MembershipStatus,
    OrganizationRole,
    OrganizationUser,
)
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.models.user import User, UserStatus
from app.models.user_unit import UserUnit
from app.services import session_revocation
from app.services.access_control import ScopeSubject
from app.services.data_token_issuance import issue_for_subject
from app.services.scope_store import ScopeStore, scope_keys
from app.utils.data_token import DataTokenIssuer, generate_ed25519_keypair_b64
from app.utils.datetime import utcnow
from tests.test_data_token_issuance import INDEX_SECRET
from tests.test_scope_store import FakeValkey


def _miembro(db, organizacion, rol=OrganizationRole.MEMBER):
    user = User(
        id=uuid4(),
        default_organization_id=organizacion.id,
        cognito_sub=f"sub-{uuid4()}",
        email=f"{uuid4().hex[:8]}@example.com",
        full_name="Miembro",
        is_master=False,
    )
    db.add(user)
    db.flush()
    db.add(
        OrganizationUser(
            organization_id=organizacion.id, user_id=user.id, role=rol.value
        )
    )
    db.commit()
    return user


def _membresia(db, organizacion, user):
    return (
        db.query(OrganizationUser)
        .filter(
            OrganizationUser.organization_id == organizacion.id,
            OrganizationUser.user_id == user.id,
        )
        .one()
    )


@pytest.fixture
def flota(db_session, test_organization_data):
    """Una unidad con dispositivo, concedida a un miembro; otro miembro sin ella.

    El owner de la organización es `test_user_data`.
    """
    unidad = Unit(id=uuid4(), organization_id=test_organization_data.id, name="U1")
    equipo = Device(device_id="9" * 15, status="asignado")
    db_session.add_all([unidad, equipo])
    db_session.flush()
    db_session.add(UnitDevice(unit_id=unidad.id, device_id=equipo.device_id))
    con_unidad = _miembro(db_session, test_organization_data)
    sin_unidad = _miembro(db_session, test_organization_data)
    db_session.add(UserUnit(user_id=con_unidad.id, unit_id=unidad.id))
    db_session.commit()
    return {"unidad": unidad, "con": con_unidad, "sin": sin_unidad}


@pytest.fixture
def revocadas(revocaciones):
    """Lo que revocaron los fixtures no cuenta."""
    revocaciones.clear()
    return revocaciones


# ---------------------------------------------------------------------------
# Usuario y membresía
# ---------------------------------------------------------------------------


def test_desactivar_usuario_revoca(db_session, test_organization_data, revocadas):
    user = _miembro(db_session, test_organization_data)
    revocadas.clear()

    user.status = UserStatus.INACTIVE.value
    db_session.commit()

    assert revocadas == [user.id]


def test_reactivar_usuario_no_revoca(db_session, test_organization_data, revocadas):
    user = _miembro(db_session, test_organization_data)
    user.status = UserStatus.INACTIVE.value
    db_session.commit()
    revocadas.clear()

    user.status = UserStatus.ACTIVE.value
    db_session.commit()

    assert revocadas == []


def test_cambiar_otra_cosa_del_usuario_no_revoca(
    db_session, test_organization_data, revocadas
):
    user = _miembro(db_session, test_organization_data)
    revocadas.clear()

    user.full_name = "Otro nombre"
    db_session.commit()

    assert revocadas == []


def test_degradar_owner_revoca(db_session, test_organization_data, revocadas):
    """Un owner ve toda la organización; un member, sólo sus unidades."""
    user = _miembro(db_session, test_organization_data, OrganizationRole.OWNER)
    revocadas.clear()

    _membresia(
        db_session, test_organization_data, user
    ).role = OrganizationRole.MEMBER.value
    db_session.commit()

    assert revocadas == [user.id]


def test_degradar_owner_con_atributo_expirado_revoca(
    db_session, test_organization_data, revocadas
):
    """Tras un commit el rol está expirado y SQLAlchemy no conoce el anterior:
    se trata como si estrechara."""
    user = _miembro(db_session, test_organization_data, OrganizationRole.OWNER)
    membresia = _membresia(db_session, test_organization_data, user)
    db_session.commit()
    revocadas.clear()

    membresia.role = OrganizationRole.MEMBER.value
    db_session.commit()

    assert revocadas == [user.id]


def test_ascender_a_owner_no_revoca(db_session, test_organization_data, revocadas):
    user = _miembro(db_session, test_organization_data)
    membresia = _membresia(db_session, test_organization_data, user)
    revocadas.clear()

    membresia.role = OrganizationRole.OWNER.value
    db_session.commit()

    assert revocadas == []


def test_pausar_membresia_revoca(db_session, test_organization_data, revocadas):
    user = _miembro(db_session, test_organization_data)
    membresia = _membresia(db_session, test_organization_data, user)
    revocadas.clear()

    membresia.status = MembershipStatus.INACTIVE.value
    db_session.commit()

    assert revocadas == [user.id]


def test_quitar_membresia_revoca(db_session, test_organization_data, revocadas):
    user = _miembro(db_session, test_organization_data)
    membresia = _membresia(db_session, test_organization_data, user)
    revocadas.clear()

    db_session.delete(membresia)
    db_session.commit()

    assert revocadas == [user.id]


# ---------------------------------------------------------------------------
# Concesiones de unidades
# ---------------------------------------------------------------------------


def test_quitar_unidad_a_usuario_revoca(db_session, flota, revocadas):
    concesion = (
        db_session.query(UserUnit).filter(UserUnit.user_id == flota["con"].id).one()
    )

    db_session.delete(concesion)
    db_session.commit()

    assert revocadas == [flota["con"].id]


def test_conceder_unidad_no_revoca(db_session, flota, revocadas):
    db_session.add(UserUnit(user_id=flota["sin"].id, unit_id=flota["unidad"].id))
    db_session.commit()

    assert revocadas == []


# ---------------------------------------------------------------------------
# Dispositivos y unidades: revoca a quien veía la unidad
# ---------------------------------------------------------------------------


def test_desasignar_dispositivo_revoca_a_quien_veia_la_unidad(
    db_session, flota, test_user_data, revocadas
):
    asignacion = (
        db_session.query(UnitDevice)
        .filter(UnitDevice.unit_id == flota["unidad"].id)
        .one()
    )

    asignacion.unassigned_at = utcnow()
    db_session.commit()

    # El miembro con la unidad y el owner; no el miembro que no la tenía.
    assert set(revocadas) == {flota["con"].id, test_user_data.id}


def test_asignar_dispositivo_no_revoca(db_session, flota, revocadas):
    otro = Device(device_id="8" * 15, status="asignado")
    db_session.add(otro)
    db_session.flush()
    db_session.add(UnitDevice(unit_id=flota["unidad"].id, device_id=otro.device_id))
    db_session.commit()

    assert revocadas == []


def test_borrar_unidad_revoca_a_quien_la_veia(
    db_session, flota, test_user_data, revocadas
):
    flota["unidad"].deleted_at = utcnow()
    db_session.commit()

    assert set(revocadas) == {flota["con"].id, test_user_data.id}


def test_un_rollback_no_revoca(db_session, flota, revocadas):
    flota["unidad"].deleted_at = utcnow()
    db_session.flush()
    db_session.rollback()

    assert revocadas == []


def test_un_fallo_del_store_no_tumba_el_commit(db_session, flota):
    def roto():
        raise RuntimeError("Valkey no responde")

    session_revocation.usar_store(roto)
    try:
        flota["unidad"].deleted_at = utcnow()
        db_session.commit()
    finally:
        session_revocation.usar_store(None)

    db_session.refresh(flota["unidad"])
    assert flota["unidad"].deleted_at is not None


# ---------------------------------------------------------------------------
# D1 de extremo a extremo, con el store real sobre un Valkey falso
# ---------------------------------------------------------------------------


@pytest.fixture
def emisor(monkeypatch):
    monkeypatch.setattr(
        "app.utils.data_token.settings.DATA_TOKEN_PRIVATE_KEY_B64",
        generate_ed25519_keypair_b64()[0],
    )
    return DataTokenIssuer()


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(
        "app.services.scope_store.settings.DATA_TOKEN_INDEX_SECRET_B64", INDEX_SECRET
    )
    valkey = FakeValkey()
    store = ScopeStore(valkey)
    session_revocation.usar_store(lambda: store)
    yield store, valkey
    session_revocation.usar_store(None)


def test_dos_emisiones_seguidas_resuelven_y_un_estrechamiento_mata_las_dos(
    db_session,
    flota,
    emisor,
    store,
):
    """El caso que motiva D1: la web y el móvil renuevan a la vez y los dos
    tokens siguen valiendo; quitarle la unidad los apaga a los dos."""
    scope_store, valkey = store
    sujeto = ScopeSubject(
        organization_id=flota["unidad"].organization_id, user_id=flota["con"].id
    )
    primero, segundo = (
        issue_for_subject(
            db_session,
            subject=sujeto,
            subject_id=flota["con"].id,
            issuer=emisor,
            store=scope_store,
        )
        for _ in range(2)
    )
    assert scope_keys(primero.scope_ref)[0] in valkey.hashes
    assert scope_keys(segundo.scope_ref)[0] in valkey.hashes

    concesion = (
        db_session.query(UserUnit).filter(UserUnit.user_id == flota["con"].id).one()
    )
    db_session.delete(concesion)
    db_session.commit()

    assert scope_keys(primero.scope_ref)[0] not in valkey.hashes
    assert scope_keys(segundo.scope_ref)[0] not in valkey.hashes


# ---------------------------------------------------------------------------
# Un usuario desactivado no autentica, aunque su token siga validando
# ---------------------------------------------------------------------------


def test_usuario_inactivo_recibe_403_aunque_su_token_valide(
    client, db_session, test_organization_data
):
    user = _miembro(db_session, test_organization_data)
    user.status = UserStatus.INACTIVE.value
    db_session.commit()

    fastapi_app.dependency_overrides[get_current_user] = lambda: {
        "sub": user.cognito_sub
    }
    respuesta = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer irrelevante"}
    )

    assert respuesta.status_code == status.HTTP_403_FORBIDDEN


def test_usuario_inactivo_no_renueva_sesion(client, db_session, test_organization_data):
    user = _miembro(db_session, test_organization_data)
    user.external_id = user.email
    user.status = UserStatus.INACTIVE.value
    db_session.commit()

    with patch(
        "app.api.v1.endpoints.auth.verificar_access_token_para_refresco",
        return_value={"sub": user.cognito_sub},
    ):
        respuesta = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "irrelevante"},
            headers={"Authorization": "Bearer viejo"},
        )

    assert respuesta.status_code == status.HTTP_401_UNAUTHORIZED

"""Una concesión da lo ocurrido mientras estuvo vigente (migración 046).

El escenario: un equipo lleva treinta días en una unidad. A un miembro se le
concede la unidad hace diez. Sin `include_history` ve desde hace diez; con él,
desde que el equipo llegó. Lo mismo vale para el data token, las alertas y los
viajes, que son los tres sitios que sirven histórico.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_current_user_full
from app.api.v1.endpoints.trips import get_auth_for_trips
from app.main import app as fastapi_app
from app.models.alert import Alert
from app.models.device import Device
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.trip import Trip
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.models.user import User
from app.models.user_unit import UserUnit, UserUnitGrantHistory
from app.services.access_control import (
    ScopeSubject,
    TimeWindow,
    accessible_refs,
    grant_windows,
)

# Con zona: una fecha ingenua la lee Postgres en la hora local de la sesión.
AHORA = datetime.now(timezone.utc)


def _hace(dias: int):
    return AHORA - timedelta(days=dias)


@pytest.fixture
def escena(db_session, test_organization_data):
    org = test_organization_data
    miembro = User(
        id=uuid4(),
        default_organization_id=org.id,
        cognito_sub=f"sub-{uuid4()}",
        email=f"{uuid4().hex[:8]}@example.com",
        full_name="Miembro",
        is_master=False,
    )
    unidad = Unit(id=uuid4(), organization_id=org.id, name="U1")
    equipo = Device(device_id="7" * 15, status="asignado")
    db_session.add_all([miembro, unidad, equipo])
    db_session.flush()
    db_session.add(
        OrganizationUser(
            organization_id=org.id,
            user_id=miembro.id,
            role=OrganizationRole.MEMBER.value,
        )
    )
    db_session.add(
        UnitDevice(unit_id=unidad.id, device_id=equipo.device_id, assigned_at=_hace(30))
    )
    db_session.commit()
    return {"org": org, "miembro": miembro, "unidad": unidad, "equipo": equipo}


def _conceder(db, escena, dias: int, historia: bool = False) -> UserUnit:
    concesion = UserUnit(
        user_id=escena["miembro"].id,
        unit_id=escena["unidad"].id,
        granted_at=_hace(dias),
        include_history=historia,
    )
    db.add(concesion)
    db.commit()
    return concesion


def _sujeto(escena):
    return ScopeSubject(organization_id=escena["org"].id, user_id=escena["miembro"].id)


def _ventanas_del_equipo(db, escena):
    refs = accessible_refs(db, _sujeto(escena))
    (grant,) = refs.devices.values()
    return grant.windows


# ---------------------------------------------------------------------------
# El alcance (data token y viajes)
# ---------------------------------------------------------------------------


def test_sin_historia_se_ve_desde_la_concesion(db_session, escena):
    _conceder(db_session, escena, dias=10)

    (ventana,) = _ventanas_del_equipo(db_session, escena)
    assert ventana.start == _hace(10)
    assert ventana.is_open


def test_con_historia_se_ve_desde_que_llego_el_equipo(db_session, escena):
    _conceder(db_session, escena, dias=10, historia=True)

    (ventana,) = _ventanas_del_equipo(db_session, escena)
    assert ventana.start == _hace(30)


def test_retirar_archiva_y_deja_de_verse(db_session, escena):
    concesion = _conceder(db_session, escena, dias=10)
    db_session.delete(concesion)
    db_session.commit()

    assert db_session.query(UserUnitGrantHistory).count() == 1
    assert accessible_refs(db_session, _sujeto(escena)).devices == {}


def test_volver_a_conceder_suma_la_ventana_de_antes(db_session, escena):
    """Tuvo la unidad de hace 20 a hace 15 días; vuelve a tenerla desde hace 5.
    Ve esos dos tramos y no el hueco de en medio."""
    concesion = _conceder(db_session, escena, dias=20)
    db_session.delete(concesion)
    db_session.commit()
    # El trigger fecha el retiro con now(), que en la transacción del test es
    # su inicio; se mueve al pasado para que el escenario sea realista.
    db_session.query(UserUnitGrantHistory).update(
        {UserUnitGrantHistory.revoked_at: _hace(15)}
    )
    _conceder(db_session, escena, dias=5)

    assert _ventanas_del_equipo(db_session, escena) == (
        TimeWindow(start=_hace(20), end=_hace(15)),
        TimeWindow(start=_hace(5)),
    )


def test_el_owner_sigue_viendolo_todo(db_session, escena):
    sujeto = ScopeSubject(organization_id=escena["org"].id)
    assert grant_windows(db_session, sujeto) == {escena["unidad"].id: (TimeWindow(),)}


def test_quitarle_la_historia_a_una_concesion_revoca(db_session, escena, revocaciones):
    concesion = _conceder(db_session, escena, dias=10, historia=True)
    revocaciones.clear()

    concesion.include_history = False
    db_session.commit()

    assert revocaciones == [escena["miembro"].id]


# ---------------------------------------------------------------------------
# Por HTTP: alertas y viajes
# ---------------------------------------------------------------------------


@pytest.fixture
def como_miembro(client, escena):
    fastapi_app.dependency_overrides[get_current_user_full] = lambda: escena["miembro"]
    return client


def _alerta(db, escena, dias: int):
    db.add(
        Alert(
            id=uuid4(),
            organization_id=escena["org"].id,
            unit_id=escena["unidad"].id,
            source_type="rule",
            type="speeding",
            occurred_at=_hace(dias),
        )
    )
    db.commit()


def test_alertas_de_antes_de_la_concesion_no_salen(db_session, escena, como_miembro):
    _conceder(db_session, escena, dias=10)
    _alerta(db_session, escena, dias=20)
    _alerta(db_session, escena, dias=5)

    for params in ({}, {"unit_id": str(escena["unidad"].id)}):
        respuesta = como_miembro.get("/api/v1/alerts", params=params)
        assert respuesta.status_code == status.HTTP_200_OK
        assert len(respuesta.json()) == 1, params


def test_alertas_con_historia_salen_todas(db_session, escena, como_miembro):
    _conceder(db_session, escena, dias=10, historia=True)
    _alerta(db_session, escena, dias=20)
    _alerta(db_session, escena, dias=5)

    respuesta = como_miembro.get("/api/v1/alerts")
    assert len(respuesta.json()) == 2


def _viaje(db, escena, dias: int) -> Trip:
    viaje = Trip(
        trip_id=uuid4(),
        device_id=escena["equipo"].device_id,
        start_time=_hace(dias),
        # Sin `end_time` el detalle da 500 (fallo aparte, anotado).
        end_time=_hace(dias) + timedelta(hours=1),
    )
    db.add(viaje)
    db.commit()
    return viaje


def test_viajes_de_la_unidad_se_recortan(db_session, escena, como_miembro):
    """Antes no recortaba ni por la concesión ni por la estancia del equipo."""
    _conceder(db_session, escena, dias=10)
    _viaje(db_session, escena, dias=20)
    _viaje(db_session, escena, dias=5)

    respuesta = como_miembro.get(
        f"/api/v1/units/{escena['unidad'].id}/trips",
        params={
            "start_date": _hace(40).isoformat(),
            "end_date": AHORA.isoformat(),
        },
    )
    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.json()["total"] == 1


def test_detalle_de_un_viaje_de_antes_da_403(db_session, escena, client):
    from app.api.deps import AuthResult

    _conceder(db_session, escena, dias=10)
    viejo = _viaje(db_session, escena, dias=20)
    nuevo = _viaje(db_session, escena, dias=5)
    fastapi_app.dependency_overrides[get_auth_for_trips] = lambda: AuthResult(
        auth_type="cognito", payload={"sub": escena["miembro"].cognito_sub}
    )

    assert (
        client.get(f"/api/v1/trips/{viejo.trip_id}").status_code
        == status.HTTP_403_FORBIDDEN
    )
    assert (
        client.get(f"/api/v1/trips/{nuevo.trip_id}").status_code == status.HTTP_200_OK
    )

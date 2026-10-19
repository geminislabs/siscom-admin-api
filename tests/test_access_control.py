"""
Tests de la resolución de alcance con sujeto explícito.

El sujeto es un parámetro, no algo que el resolver deduzca del llamante. Es lo
que permite que una futura sesión de soporte reutilice exactamente esta función
pasando otro sujeto, en vez de añadir una rama que podría ensanchar el camino
normal por error.
"""

import dataclasses
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.device import Device
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.models.user_unit import UserUnit
from app.services.access_control import (
    ScopeSubject,
    accessible_unit_ids,
    get_accessible_unit_ids,
    subject_for_user,
)


@pytest.fixture
def fleet(db_session, test_organization_data, test_user_data):
    """
    Dos unidades con dispositivo en la organización; el usuario solo tiene
    concedida la primera en `user_units`.
    """
    org_id = test_organization_data.id
    units, devices = [], []

    for i in (1, 2):
        unit = Unit(id=uuid4(), organization_id=org_id, name=f"Unidad {i}")
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

    return {"org_id": org_id, "units": units, "devices": devices}


def test_organization_subject_sees_every_unit(db_session, fleet):
    subject = ScopeSubject(organization_id=fleet["org_id"])
    assert set(accessible_unit_ids(db_session, subject)) == {
        u.id for u in fleet["units"]
    }


def test_user_subject_sees_only_granted_units(db_session, fleet, test_user_data):
    subject = ScopeSubject(organization_id=fleet["org_id"], user_id=test_user_data.id)
    assert accessible_unit_ids(db_session, subject) == [fleet["units"][0].id]


def test_deleted_units_are_excluded(db_session, fleet):
    fleet["units"][0].deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    subject = ScopeSubject(organization_id=fleet["org_id"])
    assert accessible_unit_ids(db_session, subject) == [fleet["units"][1].id]


def test_another_organization_sees_nothing(db_session, fleet):
    from app.services.access_control import accessible_refs

    subject = ScopeSubject(organization_id=uuid4())
    assert accessible_unit_ids(db_session, subject) == []
    assert accessible_refs(db_session, subject).devices == {}


def test_devices_follow_the_units_of_the_subject(db_session, fleet, test_user_data):
    from app.services.access_control import accessible_refs

    org_subject = ScopeSubject(organization_id=fleet["org_id"])
    org_refs = accessible_refs(db_session, org_subject)
    assert {g.internal_id for g in org_refs.devices.values()} == {
        d.device_id for d in fleet["devices"]
    }

    user_subject = ScopeSubject(
        organization_id=fleet["org_id"], user_id=test_user_data.id
    )
    user_refs = accessible_refs(db_session, user_subject)
    assert [g.internal_id for g in user_refs.devices.values()] == [
        fleet["devices"][0].device_id
    ]


def test_master_maps_to_an_organization_subject(test_user_data):
    test_user_data.is_master = True
    subject = subject_for_user(test_user_data)

    assert subject.is_organization_wide
    assert subject.organization_id == test_user_data.organization_id


def _hacer_miembro(db_session, user):
    """Baja la membresía del usuario a `member`: `is_master` ya no decide."""
    from app.models.organization_user import OrganizationUser

    membresia = (
        db_session.query(OrganizationUser)
        .filter(OrganizationUser.user_id == user.id)
        .one()
    )
    membresia.role = "member"
    db_session.commit()
    db_session.refresh(user)


def test_regular_user_maps_to_a_user_subject(db_session, test_user_data):
    _hacer_miembro(db_session, test_user_data)
    subject = subject_for_user(test_user_data)

    assert not subject.is_organization_wide
    assert subject.user_id == test_user_data.id


def test_subject_is_immutable(fleet):
    """Decidido el sujeto, nada aguas abajo puede ensancharlo."""
    subject = ScopeSubject(organization_id=fleet["org_id"], user_id=uuid4())
    with pytest.raises(dataclasses.FrozenInstanceError):
        subject.user_id = None  # type: ignore[misc]


def test_shortcut_matches_the_explicit_form(db_session, fleet, test_user_data):
    """
    `get_accessible_unit_ids` es solo azúcar. Si divergiera de la forma
    explícita, el modo soporte y el normal dejarían de compartir camino.
    """
    assert get_accessible_unit_ids(db_session, test_user_data) == accessible_unit_ids(
        db_session, subject_for_user(test_user_data)
    )


# ---------------------------------------------------------------------------
# Asignación activa: el plano de datos y el camino heredado difieren
# ---------------------------------------------------------------------------


def test_a_departed_device_keeps_its_history_but_loses_live_access(db_session, fleet):
    """
    El corazón de la autorización temporal. La pregunta no es "¿puede ver el
    dispositivo X?" —un booleano derivado del estado actual, incapaz de decir
    nada del pasado— sino "¿puede verlo entre t1 y t2?".

    Un dispositivo que se fue conserva su ventana cerrada: el histórico de cuando
    estuvo en la flota es legítimo. Lo que pierde es la ventana abierta, que es
    lo único que autoriza posición actual y WebSocket.
    """
    from app.services.access_control import accessible_refs

    se_fue = fleet["devices"][0]
    fila = (
        db_session.query(UnitDevice)
        .filter(UnitDevice.device_id == se_fue.device_id)
        .first()
    )
    fila.unassigned_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    db_session.commit()

    refs = accessible_refs(db_session, ScopeSubject(organization_id=fleet["org_id"]))

    # Sigue en el alcance, con su histórico acotado
    assert se_fue.device_ref in refs.devices
    concesion = refs.devices[se_fue.device_ref]
    assert concesion.internal_id == se_fue.device_id
    assert not concesion.is_live

    # El que sigue asignado conserva la ventana abierta
    assert refs.devices[fleet["devices"][1].device_ref].is_live


def test_history_is_clipped_not_rejected(db_session, fleet):
    """
    Pedir enero–diciembre habiendo tenido el equipo hasta marzo devuelve
    enero–marzo. Aquí no hay oráculo de pertenencia que proteger: el sujeto ya
    conoce los límites de su propia ventana. Distinto del rechazo total sobre
    referencias ajenas.
    """
    from app.services.access_control import accessible_refs

    device = fleet["devices"][0]
    fila = (
        db_session.query(UnitDevice)
        .filter(UnitDevice.device_id == device.device_id)
        .first()
    )
    fila.assigned_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fila.unassigned_at = datetime(2026, 3, 1, tzinfo=timezone.utc)
    db_session.commit()

    refs = accessible_refs(db_session, ScopeSubject(organization_id=fleet["org_id"]))
    recorte = refs.devices[device.device_ref].clip(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 12, 31, tzinfo=timezone.utc),
    )

    assert recorte == [
        (
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
    ]


def test_a_device_that_comes_back_gets_two_windows(db_session, fleet):
    """
    El caso que un modelo de intervalo único no puede representar: el equipo que
    se va a otro cliente y vuelve. Entre medias no hubo permiso, y ese hueco es
    exactamente lo que hay que poder expresar.
    """
    from app.services.access_control import accessible_refs

    device = fleet["devices"][0]

    primera = (
        db_session.query(UnitDevice)
        .filter(UnitDevice.device_id == device.device_id)
        .first()
    )
    primera.assigned_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    primera.unassigned_at = datetime(2026, 3, 1, tzinfo=timezone.utc)

    # Vuelve a OTRA unidad de la misma organización: `unit_devices` tiene
    # UNIQUE(unit_id, device_id), así que volver a la misma no es representable.
    db_session.add(
        UnitDevice(
            unit_id=fleet["units"][1].id,
            device_id=device.device_id,
            assigned_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            unassigned_at=None,
        )
    )
    db_session.commit()

    concesion = accessible_refs(
        db_session, ScopeSubject(organization_id=fleet["org_id"])
    ).devices[device.device_ref]

    assert len(concesion.windows) == 2
    assert concesion.is_live  # la segunda sigue abierta

    # Y el hueco de abril no se autoriza
    assert (
        concesion.clip(
            datetime(2026, 4, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        == []
    )


def test_overlapping_assignments_are_merged(db_session, fleet):
    """Dos ventanas contiguas describen el mismo permiso que una sola."""
    from app.services.access_control import accessible_refs

    device = fleet["devices"][0]

    primera = (
        db_session.query(UnitDevice)
        .filter(UnitDevice.device_id == device.device_id)
        .first()
    )
    primera.assigned_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    primera.unassigned_at = datetime(2026, 3, 1, tzinfo=timezone.utc)

    db_session.add(
        UnitDevice(
            unit_id=fleet["units"][1].id,
            device_id=device.device_id,
            assigned_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            unassigned_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    concesion = accessible_refs(
        db_session, ScopeSubject(organization_id=fleet["org_id"])
    ).devices[device.device_ref]

    assert len(concesion.windows) == 1
    assert concesion.windows[0].start == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert concesion.windows[0].end == datetime(2026, 4, 1, tzinfo=timezone.utc)


def test_units_carry_an_open_window(db_session, fleet):
    """Una unidad es de la organización de forma permanente mientras exista."""
    from app.services.access_control import accessible_refs

    refs = accessible_refs(db_session, ScopeSubject(organization_id=fleet["org_id"]))
    for unit in fleet["units"]:
        assert refs.units[unit.unit_ref].is_live


# ---------------------------------------------------------------------------
# "Sin ventanas" no puede degenerar en "sin límite"
# ---------------------------------------------------------------------------


def test_a_grant_without_windows_denies_everything():
    """
    Una tupla vacía es falsy, así que el idioma `windows or <por defecto>`
    convertiría un alcance revocado en acceso ilimitado. El fallo es del
    lenguaje, no de quien lo escribe, así que se fija por test.
    """
    from app.services.access_control import Grant

    revocado = Grant(internal_id="864537040123456", windows=())

    assert not revocado.is_live
    assert revocado.clip(None, None) == []
    assert (
        revocado.clip(
            datetime(2020, 1, 1, tzinfo=timezone.utc),
            datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
        == []
    )


def test_no_windows_and_no_limit_are_distinguishable_on_the_wire():
    """
    El plano de datos deniega ante una lista de ventanas vacía y no debe poder
    confundirla con "sin límite". Si las dos se serializaran igual, un error de
    codificación aquí se convertiría en acceso ilimitado allí.
    """
    from app.services.access_control import Grant, TimeWindow

    sin_ventanas = Grant(internal_id="X", windows=()).to_wire()
    sin_limite = Grant(internal_id="X", windows=(TimeWindow(),)).to_wire()

    assert sin_ventanas["windows"] == []
    assert sin_limite["windows"] == [{"from": None, "to": None}]
    assert sin_ventanas != sin_limite

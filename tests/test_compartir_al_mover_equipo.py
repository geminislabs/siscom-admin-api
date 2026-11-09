"""Mover un equipo de unidad apaga los enlaces de ubicación de la unidad que lo pierde.

Un enlace compartido es un data token con el `device_ref` del equipo que tenía la
unidad al compartir. Si el equipo se va, el enlace sigue mostrando ese equipo
—ya en otra unidad, o devuelto y luego en otra organización— hasta que caduque.
`unit_devices.delete_unit_device` ya lo apagaba; los otros tres caminos que
cierran una asignación, no.
"""

from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_scope_store
from app.main import app
from app.models.device import Device
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.services.scope_store import ScopePurpose
from app.utils.datetime import utcnow


class _GrabadorDeRevocaciones:
    def __init__(self):
        self.unidades = []

    def revoke_all_for_subject(self, subject_id, purpose):
        if purpose == ScopePurpose.SHARE:
            self.unidades.append(subject_id)
        return []


@pytest.fixture
def revocados(authenticated_client):
    grabador = _GrabadorDeRevocaciones()
    app.dependency_overrides[get_scope_store] = lambda: grabador
    yield grabador
    app.dependency_overrides.pop(get_scope_store, None)


@pytest.fixture
def otra_unidad(db_session, test_organization_data):
    unidad = Unit(
        id=uuid4(), organization_id=test_organization_data.id, name="Camioneta Test"
    )
    db_session.add(unidad)
    db_session.commit()
    return unidad


def _equipo(db_session, organizacion, estado, unidad=None):
    equipo = Device(
        device_id=f"86{uuid4().int % 10**13:013d}",
        brand="Queclink",
        model="GV300",
        status=estado,
        organization_id=organizacion.id,
    )
    db_session.add(equipo)
    if unidad is not None:
        db_session.add(
            UnitDevice(
                unit_id=unidad.id, device_id=equipo.device_id, assigned_at=utcnow()
            )
        )
    db_session.commit()
    return equipo


def _estado(client, equipo, nuevo, **extra):
    return client.patch(
        f"/api/v1/devices/{equipo.device_id}/status",
        json={"new_status": nuevo, **extra},
    )


def test_pasar_el_equipo_a_otra_unidad_apaga_los_enlaces_de_la_anterior(
    authenticated_client,
    revocados,
    db_session,
    test_organization_data,
    test_unit_data,
    otra_unidad,
):
    equipo = _equipo(db_session, test_organization_data, "asignado", test_unit_data)

    r = _estado(authenticated_client, equipo, "asignado", unit_id=str(otra_unidad.id))

    assert r.status_code == status.HTTP_200_OK, r.text
    assert revocados.unidades == [test_unit_data.id]


def test_reasignarlo_a_la_misma_unidad_no_apaga_nada(
    authenticated_client, revocados, db_session, test_organization_data, test_unit_data
):
    equipo = _equipo(db_session, test_organization_data, "asignado", test_unit_data)

    r = _estado(
        authenticated_client, equipo, "asignado", unit_id=str(test_unit_data.id)
    )

    assert r.status_code == status.HTTP_200_OK, r.text
    assert revocados.unidades == []


def test_devolver_el_equipo_apaga_los_enlaces_de_su_unidad(
    authenticated_client, revocados, db_session, test_organization_data, test_unit_data
):
    equipo = _equipo(db_session, test_organization_data, "asignado", test_unit_data)

    r = _estado(authenticated_client, equipo, "devuelto")

    assert r.status_code == status.HTTP_200_OK, r.text
    assert revocados.unidades == [test_unit_data.id]


def test_reemplazar_el_equipo_de_una_unidad_apaga_sus_enlaces(
    authenticated_client, revocados, db_session, test_organization_data, test_unit_data
):
    _equipo(db_session, test_organization_data, "asignado", test_unit_data)
    nuevo = _equipo(db_session, test_organization_data, "entregado")

    r = authenticated_client.post(
        f"/api/v1/units/{test_unit_data.id}/device",
        json={"device_id": nuevo.device_id},
    )

    assert r.status_code == status.HTTP_201_CREATED, r.text
    assert revocados.unidades == [test_unit_data.id]


def test_la_primera_asignacion_no_apaga_nada(
    authenticated_client, revocados, db_session, test_organization_data, test_unit_data
):
    nuevo = _equipo(db_session, test_organization_data, "entregado")

    r = authenticated_client.post(
        f"/api/v1/units/{test_unit_data.id}/device",
        json={"device_id": nuevo.device_id},
    )

    assert r.status_code == status.HTTP_201_CREATED, r.text
    assert revocados.unidades == []


def test_volver_a_una_unidad_donde_ya_estuvo_no_revienta(
    authenticated_client,
    revocados,
    db_session,
    test_organization_data,
    test_unit_data,
    otra_unidad,
):
    """`unit_devices` admite una fila por (unidad, equipo). Crear otra al volver
    a la unidad A violaba `uq_unit_devices_unit_device` y devolvía 500."""
    equipo = _equipo(db_session, test_organization_data, "asignado", test_unit_data)

    ida = _estado(authenticated_client, equipo, "asignado", unit_id=str(otra_unidad.id))
    vuelta = _estado(
        authenticated_client, equipo, "asignado", unit_id=str(test_unit_data.id)
    )

    assert ida.status_code == status.HTTP_200_OK, ida.text
    assert vuelta.status_code == status.HTTP_200_OK, vuelta.text
    activas = (
        db_session.query(UnitDevice)
        .filter(
            UnitDevice.device_id == equipo.device_id,
            UnitDevice.unassigned_at.is_(None),
        )
        .all()
    )
    assert [a.unit_id for a in activas] == [test_unit_data.id]
    assert revocados.unidades == [test_unit_data.id, otra_unidad.id]

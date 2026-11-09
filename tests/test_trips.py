from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.deps import AuthResult
from app.api.v1.endpoints import trips as trips_endpoint
from app.main import app
from app.models.trip import Trip
from app.models.unit_device import UnitDevice


def test_un_viaje_sin_terminar_no_revienta_la_respuesta():
    """Cuatro viajes de produccion tienen `end_time` NULL, y devolvian 500.

    `TripBase.end_timestamp` era obligatorio y `build_trip_out` le pasaba
    `trip.end_time` tal cual, asi que Pydantic reventaba al serializar. El
    detalle que lo delata: la linea de justo encima ya se protegia con
    `if trip.start_time and trip.end_time` para calcular la duracion — se sabia
    que podia faltar, y aun asi el campo se declaro obligatorio.

    Un viaje en curso no tiene fin. Esa es la unica lectura razonable del dato.
    """
    abierto = Trip(
        trip_id=uuid4(),
        device_id="864000000000001",
        start_time=datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc),
        end_time=None,
    )

    salida = trips_endpoint.build_trip_out(abierto)

    assert salida.end_timestamp is None
    # Y la duracion no se inventa: sin fin no hay duracion que calcular.
    assert salida.duration_minutes is None


@pytest.fixture
def gac(client):
    app.dependency_overrides[trips_endpoint.get_auth_for_trips] = lambda: AuthResult(
        auth_type="paseto",
        payload={"service": "gac", "role": "GAC_ADMIN"},
        service="gac",
        role="GAC_ADMIN",
    )
    yield client
    app.dependency_overrides.pop(trips_endpoint.get_auth_for_trips, None)


@pytest.fixture
def viaje_en_curso(db_session, test_device_data, test_unit_data):
    """Un viaje sin `end_time`, de un equipo montado en una unidad desde antes."""
    db_session.add(
        UnitDevice(
            unit_id=test_unit_data.id,
            device_id=test_device_data.device_id,
            assigned_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    )
    viaje = Trip(
        trip_id=uuid4(),
        device_id=test_device_data.device_id,
        start_time=datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc),
        end_time=None,
    )
    db_session.add(viaje)
    db_session.commit()
    return viaje


def test_el_detalle_de_un_viaje_en_curso_no_revienta(
    gac, viaje_en_curso, test_unit_data
):
    """`build_trip_detail` comparaba `assigned_at <= trip.end_time` con `end_time`
    NULL, y SQLAlchemy rechaza `<=` contra `None`: el detalle daba 500. El viaje
    cuenta hasta ahora, y su unidad es la que tiene el equipo."""
    r = gac.get(f"/api/v1/trips/{viaje_en_curso.trip_id}")

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["end_timestamp"] is None
    assert cuerpo["duration_minutes"] is None
    assert cuerpo["unit_id"] == str(test_unit_data.id)
    assert cuerpo["unit_name"] == "Camión Test"


def test_el_listado_con_expansiones_tampoco_revienta(gac, viaje_en_curso):
    """Con cualquier `include_*`, el listado arma cada viaje con
    `build_trip_detail`: un solo viaje en curso en la página tiraba la lista."""
    r = gac.get("/api/v1/trips", params={"include_alerts": True})

    assert r.status_code == 200, r.text
    ids = [t["trip_id"] for t in r.json()["trips"]]
    assert str(viaje_en_curso.trip_id) in ids

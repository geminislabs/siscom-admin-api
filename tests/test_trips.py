def test_un_viaje_sin_terminar_no_revienta_la_respuesta():
    """Cuatro viajes de produccion tienen `end_time` NULL, y devolvian 500.

    `TripBase.end_timestamp` era obligatorio y `build_trip_out` le pasaba
    `trip.end_time` tal cual, asi que Pydantic reventaba al serializar. El
    detalle que lo delata: la linea de justo encima ya se protegia con
    `if trip.start_time and trip.end_time` para calcular la duracion — se sabia
    que podia faltar, y aun asi el campo se declaro obligatorio.

    Un viaje en curso no tiene fin. Esa es la unica lectura razonable del dato.
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    from app.api.v1.endpoints.trips import build_trip_out
    from app.models.trip import Trip

    abierto = Trip(
        trip_id=uuid4(),
        device_id="864000000000001",
        start_time=datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc),
        end_time=None,
    )

    salida = build_trip_out(abierto)

    assert salida.end_timestamp is None
    # Y la duracion no se inventa: sin fin no hay duracion que calcular.
    assert salida.duration_minutes is None

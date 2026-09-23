"""Tests para app.services.health.check_kafka_accessibility."""

from unittest.mock import MagicMock

import app.services.health as health_mod
from app.core.config import settings


def test_check_kafka_returns_false_when_kafka_import_missing(monkeypatch):
    monkeypatch.setattr(health_mod, "KafkaProducer", None)

    assert health_mod.check_kafka_accessibility() is False


def test_check_kafka_returns_false_when_no_brokers(monkeypatch):
    monkeypatch.setattr(health_mod, "KafkaProducer", MagicMock())

    monkeypatch.setattr(health_mod.settings, "KAFKA_BROKERS", ", , ")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SECURITY_PROTOCOL", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_USERNAME", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_PASSWORD", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_MECHANISM", "")

    assert health_mod.check_kafka_accessibility() is False


def test_check_kafka_returns_true_when_producer_ok(monkeypatch):
    prod = MagicMock()

    kafka_cls = MagicMock(return_value=prod)

    monkeypatch.setattr(health_mod, "KafkaProducer", kafka_cls)
    monkeypatch.setattr(health_mod.settings, "KAFKA_BROKERS", "localhost:9092")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SECURITY_PROTOCOL", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_USERNAME", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_PASSWORD", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_MECHANISM", "")

    assert health_mod.check_kafka_accessibility() is True

    prod.close.assert_called_once()


def test_check_kafka_returns_false_when_kafka_raises(monkeypatch):
    monkeypatch.setattr(
        health_mod,
        "KafkaProducer",
        MagicMock(side_effect=RuntimeError("broker down")),
    )
    monkeypatch.setattr(health_mod.settings, "KAFKA_BROKERS", "localhost:9092")

    assert health_mod.check_kafka_accessibility() is False


# ---------------------------------------------------------------------------
# /health contra la base de datos
#
# El endpoint devolvia un diccionario estatico. Estas pruebas fijan que ahora
# puede fallar, que es la unica razon por la que un healthcheck sirve.
# ---------------------------------------------------------------------------


def test_check_database_ok(monkeypatch):
    import app.db.session as session_mod

    conn = MagicMock()
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    monkeypatch.setattr(session_mod, "engine", engine)

    ok, detalle = health_mod.check_database()

    assert ok is True
    assert detalle is None


def test_check_database_detecta_base_caida(monkeypatch):
    import app.db.session as session_mod

    engine = MagicMock()
    engine.connect.side_effect = RuntimeError("could not connect to server")
    monkeypatch.setattr(session_mod, "engine", engine)

    ok, detalle = health_mod.check_database()

    assert ok is False
    assert "could not connect" in detalle


def test_get_schema_revision_none_si_no_hay_alembic_version(monkeypatch):
    """Es el caso real de produccion hoy: alembic nunca gestiono el esquema."""
    import app.db.session as session_mod

    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = False
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    monkeypatch.setattr(session_mod, "engine", engine)

    assert health_mod.get_schema_revision() is None


def test_get_schema_revision_devuelve_la_revision(monkeypatch):
    import app.db.session as session_mod

    conn = MagicMock()
    conn.execute.return_value.scalar.side_effect = [True, "025_device_and_unit_refs"]
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    monkeypatch.setattr(session_mod, "engine", engine)

    assert health_mod.get_schema_revision() == "025_device_and_unit_refs"


def test_health_endpoint_devuelve_503_con_la_base_caida(client, monkeypatch):
    """El fallo que hacia inutil el healthcheck: verde con la base inservible.

    Usa el fixture `client` de conftest y no un TestClient propio: ese fixture
    stubea los productores de Kafka antes de arrancar el lifespan. Sin el, cada
    cliente nuevo intenta una conexion real a Kafka y la prueba se cuelga.
    """
    import app.main as main_mod

    # La forma real de un fallo de conexion de SQLAlchemy, que es justo lo que
    # no debe salir por el cuerpo de la respuesta.
    error_real = (
        '(psycopg2.OperationalError) connection to server at "siscom-db" '
        "(172.18.0.4), port 5432 failed: FATAL:  password authentication "
        'failed for user "siscom"'
    )
    monkeypatch.setattr(main_mod, "check_database", lambda: (False, error_real))
    monkeypatch.setattr(main_mod, "get_schema_revision", lambda: None)

    resp = client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["database"] == "unreachable"
    assert body["detail"] == "database unreachable"

    # Lo que de verdad importa: /health no exige autenticacion, asi que el
    # detalle del fallo no puede llevar host, puerto ni usuario de la conexion.
    cuerpo = resp.text
    # "siscom" a secas no entra en la lista: el payload lleva siempre
    # "service": "siscom-admin-api", que es publico a proposito.
    for filtracion in (
        "siscom-db",
        "172.18.0.4",
        "5432",
        "psycopg2",
        "password authentication",
    ):
        assert filtracion not in cuerpo, f"{filtracion!r} se filtro en /health"


def _health_body(monkeypatch):
    """Invoca health_check sin fixture client: no necesita Postgres."""
    from fastapi import Response

    import app.main as main_mod

    monkeypatch.setattr(main_mod, "check_database", lambda: (True, None))
    monkeypatch.setattr(
        main_mod, "get_schema_revision", lambda: "025_device_and_unit_refs"
    )
    return main_mod.health_check(Response())


def test_health_payload_incluye_environment_y_version(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOY_ENV", "production")
    monkeypatch.setattr(settings, "SERVICE_VERSION", "1.38.0")

    body = _health_body(monkeypatch)

    assert body["environment"] == "production"
    assert body["version"] == "1.38.0"
    assert body["status"] == "healthy"


def test_health_declara_version_desconocida_si_nadie_la_inyecta(monkeypatch):
    """El caso real de hoy: nada escribe SERVICE_VERSION en el entorno.

    La prueba anterior comparaba el payload contra `settings.SERVICE_VERSION`,
    asi que pasaba con cualquier valor — incluido un "0.1.0" por defecto que
    habria dicho eso mismo con la v1.38.0 desplegada. Lo que hay que fijar es
    que sin inyeccion el endpoint declara ignorancia, no un numero plausible.
    """
    body = _health_body(monkeypatch)

    assert body["version"] == "unknown"


def test_service_version_sale_del_fichero_del_repo():
    """La version la escribe el commit de release en `VERSION`.

    Antes salia de una variable de entorno que nadie inyectaba, asi que /health
    habria anunciado un numero inventado. Ahora sale de un fichero que el propio
    corte de release ya toca (ver docs/RELEASE.md).
    """
    from pathlib import Path

    from app.core.config import Settings

    en_el_repo = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()

    assert en_el_repo
    assert Settings.model_fields["SERVICE_VERSION"].default == en_el_repo


def test_sin_fichero_version_se_declara_desconocida(monkeypatch):
    """Si el fichero no viaja en la imagen, se dice que no se sabe."""
    from pathlib import Path

    from app.core.config import _version_del_repo

    def _explota(self, *args, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(Path, "read_text", _explota)

    assert _version_del_repo() == "unknown"


def test_health_endpoint_ok_expone_la_revision(client, monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "check_database", lambda: (True, None))
    monkeypatch.setattr(
        main_mod, "get_schema_revision", lambda: "025_device_and_unit_refs"
    )
    monkeypatch.setattr(settings, "DEPLOY_ENV", "local")
    monkeypatch.setattr(settings, "SERVICE_VERSION", "unknown")

    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["database"] == "ok"
    assert body["schema_revision"] == "025_device_and_unit_refs"
    assert body["environment"] == "local"
    assert body["version"] == "unknown"

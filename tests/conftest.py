"""Pytest configuration and shared fixtures."""

from tests.bootstrap_env import bootstrap_test_runtime

bootstrap_test_runtime()

from unittest.mock import patch
from uuid import uuid4

import pytest
import sqlalchemy
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.api.deps import (
    AuthResult,
    get_auth_for_gac_admin,
    get_current_organization_id,
    get_current_user_full,
    get_current_user_id,
    get_geofences_kafka_producer,
    get_mobility_kafka_producer,
    get_rules_kafka_producer,
    get_unit_devices_kafka_producer,
    get_user_devices_kafka_producer,
    get_user_units_kafka_producer,
)
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.account import Account
from app.models.device import Device
from app.models.organization import Organization
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.plan import Plan
from app.models.unit import Unit
from app.models.user import User

# Base de datos PostgreSQL real para los tests.
#
# Antes esto era SQLite en memoria con un parche que borraba los
# `server_default`, sustituia UUID/ARRAY/INET/JSONB por Text y aplanaba el
# schema. Ese parche hacia que la bateria no pudiera fallar por casi ninguna de
# las razones por las que falla produccion: defaults, tipos, restricciones,
# carreras (los locks consultivos eran un no-op declarado) ni migraciones.
# Ver §20 del documento de arquitectura.
DATABASE_URL = (
    f"postgresql+psycopg2://{settings.DB_USER}:{settings.DB_PASSWORD}"
    f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
)

# URL a la base de mantenimiento, para poder crear la de tests si no existe.
_ADMIN_URL = (
    f"postgresql+psycopg2://{settings.DB_USER}:{settings.DB_PASSWORD}"
    f"@{settings.DB_HOST}:{settings.DB_PORT}/postgres"
)


def _register_all_table_models() -> None:
    """Registra todos los modelos SQLModel antes de crear el esquema."""
    import app.models  # noqa: F401
    from app.api.v1.endpoints.api_platform.models import (  # noqa: F401
        api_alert,
        api_key,
        api_limit,
        api_log,
        api_throttle,
        api_usage,
    )


def _assert_es_base_de_tests() -> None:
    """Impide que el borrado de esquemas caiga sobre una base que no sea de tests.

    El fixture hace DROP SCHEMA ... CASCADE, que no perdona. El nombre debe
    delatar que es desechable.
    """
    nombre = settings.DB_NAME or ""
    if "test" not in nombre.lower():
        raise RuntimeError(
            f"DB_NAME={nombre!r} no parece una base de tests y el harness borra "
            f"esquemas enteros. Usa TEST_DB_NAME (por defecto 'siscom_test')."
        )


def _ensure_database_exists() -> None:
    """Crea la base de tests si no existe. Idempotente."""
    admin = create_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            existe = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": settings.DB_NAME},
            ).scalar()
            if not existe:
                conn.execute(text(f'CREATE DATABASE "{settings.DB_NAME}"'))
    except sqlalchemy.exc.OperationalError as exc:
        raise RuntimeError(
            f"No se pudo conectar a PostgreSQL en "
            f"{settings.DB_HOST}:{settings.DB_PORT}.\n"
            f"Los tests necesitan un Postgres real. Levantalo con:\n"
            f"    ./scripts/db-local.sh up\n"
            f"Original: {exc}"
        ) from exc
    finally:
        admin.dispose()


def _reset_schemas(engine) -> None:
    """Deja los esquemas vacios, sin depender de lo que la metadata conozca."""
    esquemas = {"public"} | {
        t.schema for t in SQLModel.metadata.tables.values() if t.schema
    }
    with engine.connect() as conn:
        for esquema in sorted(esquemas):
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{esquema}" CASCADE'))
        conn.commit()


def _create_schemas(engine) -> None:
    """Crea los esquemas de PostgreSQL que declaran los modelos.

    Hay tablas fuera de `public` — `api_platform.*` —, y `create_all()` no crea
    el esquema que las contiene. Con SQLite esto no se veia: el parche hacia
    `table.schema = None` y renombraba la tabla a `api_platform_api_alerts`,
    asi que las pruebas se ejecutaban contra una tabla en otro sitio y con otro
    nombre que el codigo de produccion nunca toca.
    """
    esquemas = {"public"} | {
        t.schema for t in SQLModel.metadata.tables.values() if t.schema
    }
    with engine.connect() as conn:
        for esquema in sorted(esquemas):
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{esquema}"'))
        conn.commit()


def _create_enum_types(engine) -> None:
    """Crea los tipos ENUM de PostgreSQL que `create_all()` no crea.

    `app/core/pg_enums.py` los declara con `create_type=False` a proposito: en
    produccion los crea el SQL crudo de la migracion 023, y SQLAlchemy solo los
    referencia. Consecuencia: **`SQLModel.metadata.create_all()` no es una
    definicion completa del esquema** — sin estos tipos falla con
    `type "payment_gateway" does not exist`.

    Con SQLite esto era invisible porque los tipos se sustituian por Text.

    Los CREATE TYPE se derivan del propio modulo para que no puedan divergir de
    lo que usan las columnas.
    """
    from sqlalchemy.dialects.postgresql import ENUM as PgEnum

    import app.core.pg_enums as pg_enums

    with engine.connect() as conn:
        for objeto in vars(pg_enums).values():
            if not isinstance(objeto, PgEnum) or not objeto.name:
                continue
            valores = ", ".join(f"'{v}'" for v in objeto.enums)
            conn.execute(
                text(
                    f"DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{objeto.name}') "
                    f"THEN CREATE TYPE {objeto.name} AS ENUM ({valores}); "
                    f"END IF; END $$;"
                )
            )
        conn.commit()


@pytest.fixture(scope="session")
def _engine():
    """Engine y esquema, una sola vez por sesion de tests.

    El esquema se crea una vez y cada test corre dentro de una transaccion que
    se revierte al terminar. Antes se hacia create_all + drop_all de 73 tablas
    *por cada test*, que en Postgres seria inviable.
    """
    _assert_es_base_de_tests()
    _ensure_database_exists()
    _register_all_table_models()

    # El reseteo va con un engine EFIMERO, y no es un detalle de estilo.
    #
    # Recrear `public` invalida el `search_path` de cualquier conexion que el
    # pool tuviera abierta de antes: al reusarla, Postgres responde
    # `no schema has been selected to create in`. Con un engine propio que se
    # desecha, el engine de la sesion nace despues y todas sus conexiones
    # resuelven el search_path sobre el esquema nuevo.
    #
    # Y se borran los esquemas enteros, no `SQLModel.metadata.drop_all()`:
    # `drop_all` solo tira lo que la metadata conoce, asi que una tabla de una
    # corrida anterior cuyo modelo ya se borro se queda huerfana, y basta con
    # que tenga una FK para que el siguiente `drop_all` falle en cascada. Paso
    # de verdad al eliminar `device_services`: su FK a `payments` impedia tirar
    # `payments`.
    preparador = create_engine(DATABASE_URL, future=True)
    try:
        _reset_schemas(preparador)
        _create_schemas(preparador)
        with preparador.connect() as conn:
            # Despues de recrear los esquemas, no antes: una extension necesita
            # un esquema donde vivir, y sin `public` falla con
            # `no schema has been selected to create in`.
            # gen_random_uuid() es nativo desde PG13; pgcrypto cubre versiones
            # anteriores y no estorba en las nuevas.
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
            conn.commit()
    finally:
        preparador.dispose()

    engine = create_engine(DATABASE_URL, future=True)
    _create_enum_types(engine)
    SQLModel.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        # No se borra al terminar: el reseteo del arranque ya garantiza pizarra
        # limpia, y dejar la base sin `public` la deja inservible para la
        # siguiente corrida. Ademas, conservar el esquema ayuda a inspeccionar
        # un fallo despues de que la bateria termine.
        engine.dispose()


class _SilentKafkaProducer:
    def publish_update(self, payload=None, key=None):
        return True

    def publish_rule_update(self, payload=None, key=None):
        return True

    def publish_location(self, payload=None, key=None):
        return True

    def close(self):
        return None


def _stub_kafka_producers():
    producer = _SilentKafkaProducer()
    app.dependency_overrides[get_user_devices_kafka_producer] = lambda: producer
    app.dependency_overrides[get_unit_devices_kafka_producer] = lambda: producer
    app.dependency_overrides[get_user_units_kafka_producer] = lambda: producer
    app.dependency_overrides[get_geofences_kafka_producer] = lambda: producer
    app.dependency_overrides[get_rules_kafka_producer] = lambda: producer
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: producer


@pytest.fixture(scope="session", autouse=True)
def _el_arranque_no_marca_a_kafka():
    """Silencia el sondeo de Kafka del `lifespan`, como ya se silencian los
    productores.

    `_stub_kafka_producers()` deja mudos los seis productores desde hace tiempo:
    la politica «los tests no hablan con Kafka» ya estaba tomada. Lo que se colo
    es que `check_kafka_accessibility()` **no es una dependencia** — vive en el
    `lifespan` de `app/main.py`, asi que ningun `dependency_overrides` lo
    alcanza. Y `client` abre `with TestClient(app)` por test, de modo que ese
    sondeo se ejecuta una vez por cada test que pida un cliente.

    Son 245 de los 849, y en CI cada uno cuesta 3,02 s clavados —el
    `api_version_auto_timeout_ms` del probe es 3000—, lo que da 740 s de los
    780 s que tarda el paso de tests. En local no se nota porque el puerto
    cerrado responde con un RST inmediato.

    Se parchea en `app.main` y no en `app.services.health` porque el `lifespan`
    resolvio el nombre al importarse; parchear el modulo de origen no cambiaria
    la referencia que ya tiene.
    """
    with patch("app.main.check_kafka_accessibility", return_value=False):
        yield


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def db_session(_engine):
    """Sesion aislada por test.

    Cada test corre dentro de una transaccion externa que se revierte al
    terminar, asi que no ve lo que escribieron los demas y no deja rastro.
    `join_transaction_mode="create_savepoint"` hace que los `commit()` de los
    fixtures y del codigo bajo prueba se traduzcan a SAVEPOINTs dentro de esa
    transaccion, en vez de escribir de verdad.
    """
    connection = _engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=connection,
        join_transaction_mode="create_savepoint",
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def client(db_session):
    """
    Cliente de prueba de FastAPI con base de datos mockeada.
    """

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    _stub_kafka_producers()

    # `client=(...)` da una direccion que Postgres acepta.
    #
    # Por defecto el TestClient se identifica con el host literal
    # "testclient", y `AuditService` guarda la IP en una columna `inet`: el
    # INSERT revienta con `invalid input syntax for type inet`. No se habia
    # visto porque ningun test ejercia un endpoint que auditara la IP; el
    # primero que lo hizo fue el de la baja de usuario, el 22/09/2026.
    #
    # No es un fallo de produccion —ahi `request.client.host` es una IP de
    # verdad—, es que el harness ponia un valor que ningun servidor ASGI real
    # pondria. §20 otra vez: un test que corre sobre datos imposibles no
    # informa de lo que pasaria.
    with TestClient(app, client=("203.0.113.10", 51234)) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def test_account_data(db_session):
    """
    Crea una cuenta de prueba en la base de datos.
    """
    account = Account(
        id=uuid4(),
        name="Test Account",
        status="ACTIVE",
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


@pytest.fixture(scope="function")
def test_organization_data(db_session, test_account_data):
    """
    Crea una organización de prueba vinculada a la cuenta.
    """
    organization = Organization(
        id=uuid4(),
        name="Test Organization",
        status="ACTIVE",
        account_id=test_account_data.id,
    )
    db_session.add(organization)
    db_session.commit()
    db_session.refresh(organization)
    return organization


# Alias de compatibilidad para tests existentes
@pytest.fixture(scope="function")
def test_client_data(test_organization_data):
    """
    DEPRECATED: Usar test_organization_data.
    Alias para compatibilidad con tests existentes.
    """
    return test_organization_data


@pytest.fixture(scope="function")
def test_user_data(db_session, test_organization_data):
    """
    Crea un usuario de prueba vinculado a la organización de prueba.
    """
    user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="test-cognito-sub-123",
        email="test@example.com",
        full_name="Test User",
        is_master=True,
    )
    db_session.add(user)
    db_session.flush()

    # La membresia OWNER explicita, que antes faltaba.
    #
    # Hasta el 22/09/2026 este fixture creaba la fila con `is_master=True` y
    # **sin membresia**, y doce tests pasaban porque el *fallback* heredado de
    # `OrganizationService.get_user_role` les devolvia OWNER. Al borrar ese
    # fallback salieron todos con 403 a la vez.
    #
    # Lo que importa no es que hubiera que arreglarlos, sino que el fixture
    # modelaba **un estado que produccion no tiene**: el contador (a) del
    # runbook de la 029 —masters con organizacion real y sin membresia— dio
    # `0` contra produccion. Los tests se apoyaban en un camino de codigo que
    # ninguna fila real recorre.
    db_session.add(
        OrganizationUser(
            organization_id=test_organization_data.id,
            user_id=user.id,
            role=OrganizationRole.OWNER.value,
        )
    )
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def test_device_data(db_session):
    """
    Crea un dispositivo de prueba en estado 'nuevo' sin organización asignada.
    """
    device = Device(
        device_id="123456789012345",
        brand="Queclink",
        model="GV300",
        firmware_version="1.0.0",
        status="nuevo",
        organization_id=None,  # Sin organización asignada inicialmente
        notes="Dispositivo de prueba",
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return device


@pytest.fixture(scope="function")
def test_unit_data(db_session, test_organization_data):
    """
    Crea una unidad (vehículo) de prueba.
    """
    unit = Unit(
        id=uuid4(),
        organization_id=test_organization_data.id,
        name="Camión Test",
        plate="ABC-123",
        type="Camión",
        description="Unidad de prueba",
    )
    db_session.add(unit)
    db_session.commit()
    db_session.refresh(unit)
    return unit


@pytest.fixture(scope="function")
def test_plan_data(db_session):
    """
    Crea un plan de prueba.
    """
    plan = Plan(
        id=uuid4(),
        name="Plan Test",
        description="Plan de prueba",
        price_monthly="299.00",
        price_yearly="2990.00",
        max_devices=10,
        history_days=30,
        ai_features=False,
        analytics_tools=False,
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


@pytest.fixture(scope="function")
def authenticated_client(client, test_organization_data, test_user_data):
    """
    Cliente autenticado que bypasea la validación de Cognito.
    """

    def override_get_current_organization_id():
        return test_organization_data.id

    def override_get_current_user_full():
        return test_user_data

    def override_get_current_user_id():
        return test_user_data.id

    def override_get_auth_for_gac_admin():
        return AuthResult(
            auth_type="cognito",
            payload={"sub": test_user_data.cognito_sub},
            user_id=test_user_data.id,
            organization_id=test_organization_data.id,
        )

    app.dependency_overrides[get_current_organization_id] = (
        override_get_current_organization_id
    )
    app.dependency_overrides[get_current_user_full] = override_get_current_user_full
    app.dependency_overrides[get_current_user_id] = override_get_current_user_id
    app.dependency_overrides[get_auth_for_gac_admin] = override_get_auth_for_gac_admin
    _stub_kafka_producers()

    yield client

    app.dependency_overrides.clear()

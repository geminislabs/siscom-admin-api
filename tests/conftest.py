import uuid as _uuid_module
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import JSON, Text, TypeDecorator, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.schema import ColumnDefault
from sqlmodel import SQLModel

from app.api.deps import (
    AuthResult,
    get_auth_for_gac_admin,
    get_current_organization_id,
    get_current_user_full,
    get_current_user_id,
)
from app.db.session import get_db
from app.main import app
from app.models.account import Account
from app.models.device import Device
from app.models.organization import Organization
from app.models.plan import Plan
from app.models.unit import Unit
from app.models.user import User

# Base de datos SQLite en memoria para tests (engine aislado por fixture)
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

_METADATA_PATCH_STATE = {"applied": False, "saved": None}


def _register_all_table_models() -> None:
    """Registra todos los modelos SQLModel antes de parchear metadata para SQLite."""
    import app.models  # noqa: F401
    from app.api.v1.endpoints.api_platform.models import (  # noqa: F401
        api_alert,
        api_key,
        api_limit,
        api_log,
        api_throttle,
        api_usage,
    )


def _ensure_sqlite_metadata() -> None:
    """Parchea metadata una vez por sesión para evitar drift entre tests unitarios y DB."""
    if _METADATA_PATCH_STATE["applied"]:
        return
    _register_all_table_models()
    _METADATA_PATCH_STATE["saved"] = _patch_metadata(SQLModel.metadata)
    _METADATA_PATCH_STATE["applied"] = True


@pytest.fixture(scope="session", autouse=True)
def _sqlite_test_metadata():
    _ensure_sqlite_metadata()
    yield
    saved = _METADATA_PATCH_STATE["saved"]
    if saved is not None:
        _restore_metadata(SQLModel.metadata, saved)
        _METADATA_PATCH_STATE["applied"] = False
        _METADATA_PATCH_STATE["saved"] = None


def _create_test_engine():
    return create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


class _SQLiteUUID(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return _uuid_module.UUID(str(value))
        except (ValueError, AttributeError):
            return value


_PG_TYPE_REPLACEMENTS = {}
try:
    from sqlalchemy.dialects.postgresql import ARRAY, CIDR, INET, JSONB
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    _PG_TYPE_REPLACEMENTS = {
        JSONB: JSON(),
        PG_UUID: _SQLiteUUID(),
        ARRAY: Text(),
        INET: Text(),
        CIDR: Text(),
    }
except ImportError:
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _python_default_for(server_default_text: str):
    text = server_default_text.lower()
    if any(k in text for k in ("gen_random_uuid", "uuid_generate")):
        return uuid4
    if any(k in text for k in ("now()", "current_timestamp", "timezone(")):
        return _utcnow
    return None


def _patch_metadata(metadata) -> dict:
    """Elimina server_defaults PG y reemplaza tipos PG con equivalentes SQLite."""
    saved = {}
    for table in metadata.tables.values():
        table_id = id(table)
        if table.schema is not None:
            saved[(table_id, "__table_schema__")] = {
                "schema": table.schema,
                "name": table.name,
            }
            table.name = f"{table.schema}_{table.name}"
            table.schema = None

        for column in table.columns:
            col_save = {}

            if column.server_default is not None:
                sd_text = str(getattr(column.server_default, "arg", ""))
                col_save["server_default"] = column.server_default
                column.server_default = None
                if column.default is None:
                    callable_default = _python_default_for(sd_text)
                    if callable_default:
                        col_save["default"] = column.default
                        column.default = ColumnDefault(callable_default)

            for pg_type, sqlite_type in _PG_TYPE_REPLACEMENTS.items():
                if isinstance(column.type, pg_type):
                    col_save["type"] = column.type
                    column.type = sqlite_type
                    break

            if col_save:
                saved[(table_id, column.name)] = col_save

    return saved


def _restore_metadata(metadata, saved: dict) -> None:
    """Restaura server_defaults y tipos originales."""
    for table in metadata.tables.values():
        table_id = id(table)
        schema_key = (table_id, "__table_schema__")
        if schema_key in saved:
            if "name" in saved[schema_key]:
                table.name = saved[schema_key]["name"]
            if "schema" in saved[schema_key]:
                table.schema = saved[schema_key]["schema"]

        for column in table.columns:
            key = (table_id, column.name)
            if key in saved:
                if "server_default" in saved[key]:
                    column.server_default = saved[key]["server_default"]
                if "default" in saved[key]:
                    column.default = saved[key]["default"]
                if "type" in saved[key]:
                    column.type = saved[key]["type"]


@pytest.fixture(scope="function")
def db_session():
    """
    Crea una nueva sesión de base de datos para cada test.
    """
    _ensure_sqlite_metadata()
    test_engine = _create_test_engine()
    try:
        SQLModel.metadata.create_all(bind=test_engine)
    except Exception:
        test_engine.dispose()
        raise

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        SQLModel.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


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

    with TestClient(app) as test_client:
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

    yield client

    app.dependency_overrides.clear()

"""
Tests de Telemetría Agregada.

Estrategia:
  1. Tests de schema: validan reglas de negocio puras (sin DB).
  2. Tests de acceso: mock de queries SQLAlchemy para evitar dependencia
     de DDL PostgreSQL-específico incompatible con SQLite en memoria.
  3. Tests de endpoints: mock completo sobre el servicio + DB mock
     para endpoints thin con FastAPI TestClient.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import (
    get_current_organization_id,
    get_current_user_full,
    get_current_user_id,
)
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.schemas.telemetry import (
    AlertsOut,
    AvgMinMaxOut,
    BatteryOut,
    OdometerOut,
    SpeedOut,
    TelemetryDeviceItemOut,
    TelemetryPointOut,
    TelemetryQueryRequest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(is_master: bool = True):
    org_id = uuid4()
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.organization_id = org_id
    user.cognito_sub = "test-sub"
    user.email = "test@test.com"
    user.full_name = "Test User"
    # La visibilidad sale de la membresía (`is_active_organization_owner`),
    # no de `is_master`; el parámetro conserva el nombre de los tests.
    user.is_master = is_master
    user.is_active_organization_owner = is_master
    return user


NOW = datetime(2026, 4, 21, 10, 0, 0, tzinfo=timezone.utc)
FROM_TS = NOW - timedelta(hours=3)
TO_TS = NOW


def iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_point(bucket: datetime) -> TelemetryPointOut:
    return TelemetryPointOut(
        bucket=bucket,
        speed=SpeedOut(avg_speed=55.0, min_speed=10.0, max_speed=90.0),
        main_battery=BatteryOut(avg_voltage=12.5, min_voltage=11.8, max_voltage=13.1),
        backup_battery=BatteryOut(avg_voltage=4.2, min_voltage=3.9, max_voltage=4.4),
        alerts=AlertsOut(count=2),
        signal=AvgMinMaxOut(avg=-67.5, min=-89.0, max=-51.0),
        satellites=AvgMinMaxOut(avg=8.5, min=5.0, max=12.0),
        odometer=OdometerOut(total_distance_mt=1250.0),
    )


MOCK_SERIES: List[TelemetryPointOut] = [
    _make_point(FROM_TS + timedelta(hours=i)) for i in range(3)
]

MOCK_BATCH: List[TelemetryDeviceItemOut] = [
    TelemetryDeviceItemOut(device_id="DEV-001", series=MOCK_SERIES),
    TelemetryDeviceItemOut(device_id="DEV-002", series=[_make_point(FROM_TS)]),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def master_user():
    return _make_user(is_master=True)


@pytest.fixture
def regular_user():
    return _make_user(is_master=False)


@pytest.fixture
def api_client(client, master_user):
    """Reutiliza el TestClient compartido con auth master y DB mockeada."""
    db_mock = MagicMock()

    def override_get_db():
        yield db_mock

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_full] = lambda: master_user
    app.dependency_overrides[get_current_organization_id] = lambda: (
        master_user.organization_id
    )
    app.dependency_overrides[get_current_user_id] = lambda: master_user.id

    yield client


# ===========================================================================
# 1. Tests de Schemas (validación pura, sin DB)
# ===========================================================================


class TestTelemetryQueryRequestValidation:
    def _make(self, **overrides):
        base = {
            "device_ids": ["DEV-001"],
            "from": FROM_TS.isoformat(),
            "to": TO_TS.isoformat(),
            "granularity": "hour",
            "metrics": ["speed"],
        }
        base.update(overrides)
        return base

    def test_valid_request(self):
        req = TelemetryQueryRequest.model_validate(self._make())
        assert req.device_ids == ["DEV-001"]
        assert req.granularity == "hour"
        assert req.metrics == ["speed"]

    def test_from_must_be_before_to(self):
        with pytest.raises(Exception, match="anterior"):
            TelemetryQueryRequest.model_validate(
                self._make(**{"from": TO_TS.isoformat(), "to": FROM_TS.isoformat()})
            )

    def test_from_equal_to_is_invalid(self):
        with pytest.raises(Exception, match="anterior"):
            TelemetryQueryRequest.model_validate(
                self._make(**{"from": FROM_TS.isoformat(), "to": FROM_TS.isoformat()})
            )

    def test_hour_range_exceeds_7_days(self):
        far_to = FROM_TS + timedelta(days=8)
        with pytest.raises(Exception, match="7 días"):
            TelemetryQueryRequest.model_validate(
                self._make(granularity="hour", **{"to": far_to.isoformat()})
            )

    def test_day_range_exceeds_180_days(self):
        far_to = FROM_TS + timedelta(days=181)
        with pytest.raises(Exception, match="180 días"):
            TelemetryQueryRequest.model_validate(
                self._make(granularity="day", **{"to": far_to.isoformat()})
            )

    def test_day_range_within_180_days_is_valid(self):
        far_to = FROM_TS + timedelta(days=90)
        req = TelemetryQueryRequest.model_validate(
            self._make(granularity="day", **{"to": far_to.isoformat()})
        )
        assert req.granularity == "day"

    def test_invalid_metric_raises(self):
        with pytest.raises(Exception, match="Input should be"):
            TelemetryQueryRequest.model_validate(self._make(metrics=["invalid_metric"]))

    def test_metrics_deduplication(self):
        req = TelemetryQueryRequest.model_validate(
            self._make(metrics=["speed", "speed", "alerts"])
        )
        assert req.metrics == ["speed", "alerts"]

    def test_device_ids_deduplication(self):
        req = TelemetryQueryRequest.model_validate(
            self._make(device_ids=["DEV-001", "DEV-001", "DEV-002"])
        )
        assert req.device_ids == ["DEV-001", "DEV-002"]

    def test_too_many_device_ids(self):
        ids = [f"DEV-{i:03d}" for i in range(51)]
        with pytest.raises(Exception, match="máximo"):
            TelemetryQueryRequest.model_validate(self._make(device_ids=ids))

    def test_empty_metrics_is_invalid(self):
        with pytest.raises(Exception, match="at least 1 item"):
            TelemetryQueryRequest.model_validate(self._make(metrics=[]))

    def test_all_valid_metrics_accepted(self):
        all_metrics = [
            "speed",
            "main_battery",
            "backup_battery",
            "alerts",
            "comm_quality",
            "samples",
            "signal",
            "satellites",
            "odometer",
            "fuel_consumed_liters",
            "moving_minutes",
            "idle_minutes",
        ]
        req = TelemetryQueryRequest.model_validate(self._make(metrics=all_metrics))
        assert len(req.metrics) == 12


# ===========================================================================
# 2. Tests de control de acceso (con mocks de SQLAlchemy)
# ===========================================================================


class TestTelemetryAccessControl:
    """
    Tests de la lógica de acceso usando mocks del ORM.
    Evita SQLite por incompatibilidad con DDL PostgreSQL en los modelos.
    """

    def _make_db_with_rows(self, rows):
        """Mock de db que devuelve rows en query().filter().distinct().all()"""
        mock_db = MagicMock()
        mock_db.query.return_value.join.return_value.filter.return_value.distinct.return_value.all.return_value = (
            rows
        )
        mock_db.query.return_value.filter.return_value.distinct.return_value.all.return_value = (
            rows
        )
        return mock_db

    @staticmethod
    def _refs(**concesiones):
        """AccessibleRefs con las concesiones dadas: internal_id -> ventanas."""
        from uuid import uuid4

        from app.services.access_control import AccessibleRefs, Grant

        return AccessibleRefs(
            units={},
            devices={
                uuid4(): Grant(internal_id=internal_id, windows=windows)
                for internal_id, windows in concesiones.items()
            },
        )

    def test_validate_device_access_passes_for_accessible_device(self):
        from app.services.access_control import TimeWindow
        from app.services.telemetry import validate_device_access

        user = _make_user(is_master=True)
        refs = self._refs(**{"DEV-001": (TimeWindow(),)})

        with patch("app.services.telemetry.accessible_refs", return_value=refs):
            rangos = validate_device_access(
                MagicMock(),
                user,
                "DEV-001",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 2, 1, tzinfo=timezone.utc),
            )

        assert rangos  # ventana abierta: todo el rango pedido está autorizado

    def test_validate_device_access_raises_404_for_inaccessible(self):
        from fastapi import HTTPException

        from app.services.access_control import TimeWindow
        from app.services.telemetry import validate_device_access

        user = _make_user(is_master=False)
        refs = self._refs(**{"DEV-ALLOWED": (TimeWindow(),)})

        with patch("app.services.telemetry.accessible_refs", return_value=refs):
            with pytest.raises(HTTPException) as exc_info:
                validate_device_access(
                    MagicMock(),
                    user,
                    "DEV-FORBIDDEN",
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    datetime(2026, 2, 1, tzinfo=timezone.utc),
                )
        assert exc_info.value.status_code == 404

    def test_access_outside_the_window_is_404_not_an_empty_series(self):
        """
        Pedir un rango entero posterior a la marcha del equipo no es "sin datos":
        es "no tienes permiso ahí". Devolver una serie vacía confundiría la
        ausencia de permiso con la ausencia de datos.
        """
        from fastapi import HTTPException

        from app.services.access_control import TimeWindow
        from app.services.telemetry import validate_device_access

        user = _make_user(is_master=True)
        refs = self._refs(
            **{
                "DEV-001": (
                    TimeWindow(
                        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        end=datetime(2026, 3, 1, tzinfo=timezone.utc),
                    ),
                )
            }
        )

        with patch("app.services.telemetry.accessible_refs", return_value=refs):
            with pytest.raises(HTTPException) as exc_info:
                validate_device_access(
                    MagicMock(),
                    user,
                    "DEV-001",
                    datetime(2026, 6, 1, tzinfo=timezone.utc),
                    datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
        assert exc_info.value.status_code == 404

    def test_a_partially_covered_range_is_clipped_not_rejected(self):
        """Enero–diciembre con el equipo hasta marzo devuelve enero–marzo."""
        from app.services.access_control import TimeWindow
        from app.services.telemetry import validate_device_access

        user = _make_user(is_master=True)
        fin = datetime(2026, 3, 1, tzinfo=timezone.utc)
        refs = self._refs(
            **{
                "DEV-001": (
                    TimeWindow(
                        start=datetime(2026, 1, 1, tzinfo=timezone.utc), end=fin
                    ),
                )
            }
        )

        with patch("app.services.telemetry.accessible_refs", return_value=refs):
            rangos = validate_device_access(
                MagicMock(),
                user,
                "DEV-001",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 12, 31, tzinfo=timezone.utc),
            )

        assert rangos == [(datetime(2026, 1, 1, tzinfo=timezone.utc), fin)]

    def test_batch_rejects_the_whole_request_if_any_is_unauthorised(self):
        from fastapi import HTTPException

        from app.services.access_control import TimeWindow
        from app.services.telemetry import _authorized_ranges_for_batch

        user = _make_user(is_master=True)
        refs = self._refs(**{"DEV-001": (TimeWindow(),)})

        with patch("app.services.telemetry.accessible_refs", return_value=refs):
            with pytest.raises(HTTPException) as exc_info:
                _authorized_ranges_for_batch(
                    MagicMock(),
                    user,
                    ["DEV-001", "DEV-AJENO"],
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    datetime(2026, 2, 1, tzinfo=timezone.utc),
                )
        assert exc_info.value.status_code == 404

    def test_batch_passes_when_all_are_authorised(self):
        from app.services.access_control import TimeWindow
        from app.services.telemetry import _authorized_ranges_for_batch

        user = _make_user(is_master=True)
        refs = self._refs(**{"DEV-001": (TimeWindow(),), "DEV-002": (TimeWindow(),)})

        with patch("app.services.telemetry.accessible_refs", return_value=refs):
            rangos = _authorized_ranges_for_batch(
                MagicMock(),
                user,
                ["DEV-001", "DEV-002"],
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 2, 1, tzinfo=timezone.utc),
            )

        assert set(rangos) == {"DEV-001", "DEV-002"}

    def test_a_master_becomes_an_organization_wide_subject(self):
        """
        La resolución vive en `access_control` con el sujeto explícito; aquí solo
        se comprueba que telemetría traduce el usuario a su sujeto y delega.
        """
        import app.services.telemetry as tel_mod
        from app.services.access_control import AccessibleRefs

        user = _make_user(is_master=True)
        visto = {}

        def fake_refs(db, subject):
            visto["subject"] = subject
            return AccessibleRefs(units={}, devices={})

        with patch.object(tel_mod, "accessible_refs", fake_refs):
            tel_mod.authorized_ranges(MagicMock(), user, "X", None, None)

        assert visto["subject"].is_organization_wide
        assert visto["subject"].organization_id == user.organization_id

    def test_a_regular_user_becomes_a_user_scoped_subject(self):
        import app.services.telemetry as tel_mod
        from app.services.access_control import AccessibleRefs

        user = _make_user(is_master=False)
        visto = {}

        def fake_refs(db, subject):
            visto["subject"] = subject
            return AccessibleRefs(units={}, devices={})

        with patch.object(tel_mod, "accessible_refs", fake_refs):
            tel_mod.authorized_ranges(MagicMock(), user, "X", None, None)

        assert not visto["subject"].is_organization_wide
        assert visto["subject"].user_id == user.id


# ===========================================================================
# 3. Tests de endpoints (mock sobre el servicio)
# ===========================================================================


class TestGetDeviceTelemetryEndpoint:
    """
    Usa params= dict en lugar de f-strings para la URL para que httpx
    haga URL-encoding correcto del '+' en timezone offsets ISO 8601.
    """

    def _params(self, metrics=("speed",), granularity="hour", **overrides):
        """Construye params base para GET /devices/{id}/telemetry."""
        p = [
            ("from", iso(FROM_TS)),
            ("to", iso(TO_TS)),
            ("granularity", granularity),
        ]
        for m in metrics:
            p.append(("metrics", m))
        for k, v in overrides.items():
            p.append((k.replace("_", ""), v))
        return p

    def test_returns_200_with_valid_series(self, api_client):
        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_single",
            return_value=MOCK_SERIES,
        ):
            resp = api_client.get(
                "/api/v1/devices/DEV-001/telemetry",
                params=[
                    ("from", iso(FROM_TS)),
                    ("to", iso(TO_TS)),
                    ("granularity", "hour"),
                    ("metrics", "speed"),
                    ("metrics", "alerts"),
                ],
            )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["device_id"] == "DEV-001"
        assert data["granularity"] == "hour"
        assert "speed" in data["metrics"]
        assert "alerts" in data["metrics"]
        assert len(data["series"]) == 3

    def test_series_ordered_by_bucket_asc(self, api_client):
        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_single",
            return_value=MOCK_SERIES,
        ):
            resp = api_client.get(
                "/api/v1/devices/DEV-001/telemetry",
                params=[
                    ("from", iso(FROM_TS)),
                    ("to", iso(TO_TS)),
                    ("metrics", "speed"),
                ],
            )

        buckets = [s["bucket"] for s in resp.json()["series"]]
        assert buckets == sorted(buckets)

    def test_no_unrequested_metrics_in_response(self, api_client):
        series = [
            TelemetryPointOut(
                bucket=FROM_TS,
                speed=SpeedOut(avg_speed=60.0, min_speed=20.0, max_speed=90.0),
            )
        ]
        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_single",
            return_value=series,
        ):
            resp = api_client.get(
                "/api/v1/devices/DEV-001/telemetry",
                params=[
                    ("from", iso(FROM_TS)),
                    ("to", iso(TO_TS)),
                    ("metrics", "speed"),
                ],
            )

        point = resp.json()["series"][0]
        assert "speed" in point
        assert "alerts" not in point
        assert "main_battery" not in point

    def test_response_serializes_new_metrics_shape(self, api_client):
        point = TelemetryPointOut(
            bucket=FROM_TS,
            speed=SpeedOut(avg_speed=60.0, min_speed=20.0, max_speed=90.0),
            main_battery=BatteryOut(
                avg_voltage=12.4,
                min_voltage=11.9,
                max_voltage=13.0,
            ),
            backup_battery=BatteryOut(
                avg_voltage=4.1,
                min_voltage=3.8,
                max_voltage=4.3,
            ),
            signal=AvgMinMaxOut(avg=-65.0, min=-88.0, max=-49.0),
            satellites=AvgMinMaxOut(avg=7.5, min=4.0, max=10.0),
            odometer=OdometerOut(total_distance_mt=2400.0),
        )

        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_single",
            return_value=[point],
        ):
            resp = api_client.get(
                "/api/v1/devices/DEV-001/telemetry",
                params=[
                    ("from", iso(FROM_TS)),
                    ("to", iso(TO_TS)),
                    ("metrics", "speed"),
                    ("metrics", "main_battery"),
                    ("metrics", "backup_battery"),
                    ("metrics", "signal"),
                    ("metrics", "satellites"),
                    ("metrics", "odometer"),
                ],
            )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()["series"][0]
        assert data["speed"]["min_speed"] == 20.0
        assert data["main_battery"]["max_voltage"] == 13.0
        assert data["backup_battery"]["max_voltage"] == 4.3
        assert data["signal"] == {"avg": -65.0, "min": -88.0, "max": -49.0}
        assert data["satellites"] == {"avg": 7.5, "min": 4.0, "max": 10.0}
        assert data["odometer"]["total_distance_mt"] == 2400.0

    def test_empty_series_is_valid(self, api_client):
        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_single",
            return_value=[],
        ):
            resp = api_client.get(
                "/api/v1/devices/DEV-001/telemetry",
                params=[
                    ("from", iso(FROM_TS)),
                    ("to", iso(TO_TS)),
                    ("metrics", "speed"),
                ],
            )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["series"] == []

    def test_invalid_granularity_returns_422(self, api_client):
        resp = api_client.get(
            "/api/v1/devices/DEV-001/telemetry",
            params=[
                ("from", iso(FROM_TS)),
                ("to", iso(TO_TS)),
                ("granularity", "week"),
                ("metrics", "speed"),
            ],
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_range_exceeds_7_days_for_hour_returns_400(self, api_client):
        far_to = FROM_TS + timedelta(days=8)
        resp = api_client.get(
            "/api/v1/devices/DEV-001/telemetry",
            params=[
                ("from", iso(FROM_TS)),
                ("to", iso(far_to)),
                ("granularity", "hour"),
                ("metrics", "speed"),
            ],
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_from_after_to_returns_400(self, api_client):
        resp = api_client.get(
            "/api/v1/devices/DEV-001/telemetry",
            params=[("from", iso(TO_TS)), ("to", iso(FROM_TS)), ("metrics", "speed")],
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_metric_returns_422(self, api_client):
        # FastAPI valida el Literal antes de llamar al handler → 422
        resp = api_client.get(
            "/api/v1/devices/DEV-001/telemetry",
            params=[
                ("from", iso(FROM_TS)),
                ("to", iso(TO_TS)),
                ("metrics", "temperatura"),
            ],
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_get_accepts_new_intelligence_metrics(self, api_client):
        point = TelemetryPointOut(
            bucket=FROM_TS,
            fuel_consumed_liters=1.2,
            moving_minutes=44.0,
            idle_minutes=16.0,
        )

        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_single",
            return_value=[point],
        ):
            resp = api_client.get(
                "/api/v1/devices/DEV-001/telemetry",
                params=[
                    ("from", iso(FROM_TS)),
                    ("to", iso(TO_TS)),
                    ("metrics", "fuel_consumed_liters"),
                    ("metrics", "moving_minutes"),
                    ("metrics", "idle_minutes"),
                ],
            )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["metrics"] == [
            "fuel_consumed_liters",
            "moving_minutes",
            "idle_minutes",
        ]
        series_point = data["series"][0]
        assert series_point["fuel_consumed_liters"] == 1.2
        assert series_point["moving_minutes"] == 44.0
        assert series_point["idle_minutes"] == 16.0

    def test_no_metrics_param_returns_400(self, api_client):
        # FastAPI trata List[X]=Query(...) sin valor como lista vacía [];
        # _validate_single_request detecta métricas vacías y lanza 400.
        resp = api_client.get(
            "/api/v1/devices/DEV-001/telemetry",
            params=[("from", iso(FROM_TS)), ("to", iso(TO_TS))],
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_access_returns_404(self, api_client):
        from fastapi import HTTPException

        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_single",
            side_effect=HTTPException(
                status_code=404, detail="Dispositivo no encontrado"
            ),
        ):
            resp = api_client.get(
                "/api/v1/devices/DEV-FORBIDDEN/telemetry",
                params=[
                    ("from", iso(FROM_TS)),
                    ("to", iso(TO_TS)),
                    ("metrics", "speed"),
                ],
            )

        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_response_contains_from_to_fields(self, api_client):
        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_single",
            return_value=[],
        ):
            resp = api_client.get(
                "/api/v1/devices/DEV-001/telemetry",
                params=[
                    ("from", iso(FROM_TS)),
                    ("to", iso(TO_TS)),
                    ("metrics", "speed"),
                ],
            )

        data = resp.json()
        assert "from" in data
        assert "to" in data


class TestQueryTelemetryBatchEndpoint:
    def _body(self, **overrides):
        base = {
            "device_ids": ["DEV-001", "DEV-002"],
            "from": iso(FROM_TS),
            "to": iso(TO_TS),
            "granularity": "hour",
            "metrics": ["speed", "alerts"],
        }
        base.update(overrides)
        return base

    def test_returns_200_with_devices_list(self, api_client):
        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_batch",
            return_value=MOCK_BATCH,
        ):
            resp = api_client.post("/api/v1/telemetry/query", json=self._body())

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert "devices" in data
        assert len(data["devices"]) == 2

    def test_response_preserves_device_order(self, api_client):
        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_batch",
            return_value=MOCK_BATCH,
        ):
            resp = api_client.post("/api/v1/telemetry/query", json=self._body())

        ids = [d["device_id"] for d in resp.json()["devices"]]
        assert ids == ["DEV-001", "DEV-002"]

    def test_each_device_has_series(self, api_client):
        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_batch",
            return_value=MOCK_BATCH,
        ):
            resp = api_client.post("/api/v1/telemetry/query", json=self._body())

        for device in resp.json()["devices"]:
            assert "series" in device
            assert isinstance(device["series"], list)

    def test_invalid_range_returns_422(self, api_client):
        body = self._body()
        body["from"] = iso(TO_TS)
        body["to"] = iso(FROM_TS)
        resp = api_client.post("/api/v1/telemetry/query", json=body)
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_unauthorized_device_returns_404(self, api_client):
        from fastapi import HTTPException

        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_batch",
            side_effect=HTTPException(
                status_code=404, detail="Uno o más dispositivos no encontrados"
            ),
        ):
            resp = api_client.post(
                "/api/v1/telemetry/query",
                json=self._body(device_ids=["DEV-001", "DEV-FORBIDDEN"]),
            )

        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_empty_device_ids_returns_422(self, api_client):
        resp = api_client.post(
            "/api/v1/telemetry/query", json=self._body(device_ids=[])
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_too_many_devices_returns_422(self, api_client):
        ids = [f"DEV-{i:03d}" for i in range(51)]
        resp = api_client.post(
            "/api/v1/telemetry/query", json=self._body(device_ids=ids)
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_hour_range_exceeds_7_days_returns_422(self, api_client):
        far_to = FROM_TS + timedelta(days=8)
        body = self._body(granularity="hour")
        body["to"] = iso(far_to)
        resp = api_client.post("/api/v1/telemetry/query", json=body)
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_granularity_day_accepted_within_180_days(self, api_client):
        far_to = FROM_TS + timedelta(days=90)
        body = self._body(granularity="day")
        body["to"] = iso(far_to)
        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_batch",
            return_value=MOCK_BATCH,
        ):
            resp = api_client.post("/api/v1/telemetry/query", json=body)
        assert resp.status_code == status.HTTP_200_OK

    def test_response_metadata_fields(self, api_client):
        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_batch",
            return_value=MOCK_BATCH,
        ):
            resp = api_client.post("/api/v1/telemetry/query", json=self._body())

        data = resp.json()
        assert "granularity" in data
        assert "from" in data
        assert "to" in data
        assert "metrics" in data

    def test_accepts_new_intelligence_metrics(self, api_client):
        point = TelemetryPointOut(
            bucket=FROM_TS,
            fuel_consumed_liters=2.75,
            moving_minutes=38.0,
            idle_minutes=12.0,
        )
        mocked_batch = [TelemetryDeviceItemOut(device_id="DEV-001", series=[point])]

        with patch(
            "app.api.v1.endpoints.telemetry.get_telemetry_batch",
            return_value=mocked_batch,
        ):
            resp = api_client.post(
                "/api/v1/telemetry/query",
                json=self._body(
                    device_ids=["DEV-001"],
                    metrics=[
                        "fuel_consumed_liters",
                        "moving_minutes",
                        "idle_minutes",
                    ],
                ),
            )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["metrics"] == [
            "fuel_consumed_liters",
            "moving_minutes",
            "idle_minutes",
        ]
        series_point = data["devices"][0]["series"][0]
        assert series_point["fuel_consumed_liters"] == 2.75
        assert series_point["moving_minutes"] == 38.0
        assert series_point["idle_minutes"] == 12.0

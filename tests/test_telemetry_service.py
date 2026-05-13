"""Tests del núcleo de app.services.telemetry (columnas SQL, mapeo y agrupación)."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.user import User
from app.services import telemetry as tel_mod
from app.services.telemetry import (
    _build_select_columns,
    _group_rows_by_device,
    _map_row_to_point,
    validate_batch_device_access,
    validate_device_access,
)


def test_build_select_columns_includes_requested_metric_fragments():
    cols = _build_select_columns(
        ["speed", "main_battery", "alerts", "odometer"],
    )
    assert "avg_speed" in cols
    assert "avg_main_voltage" in cols
    assert "count_alerts" in cols
    assert "first_odometer" in cols


def test_build_select_columns_empty_when_no_metrics():
    assert _build_select_columns([]) == ""


def test_map_row_to_point_builds_nested_models():
    bucket = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    row = MagicMock()
    row._mapping = {
        "bucket": bucket,
        "avg_speed": 40.0,
        "min_speed": 30.0,
        "max_speed": 50.0,
        "avg_main_voltage": 12.0,
        "min_main_voltage": 11.0,
        "max_main_voltage": 13.0,
        "count_alerts": 3,
        "count_comm_fixable": 1,
        "count_comm_with_fix": 2,
        "samples": 100,
        "avg_rx_lvl": -70.0,
        "min_rx_lvl": -80.0,
        "max_rx_lvl": -60.0,
        "avg_satellites": 8.0,
        "min_satellites": 6.0,
        "max_satellites": 10.0,
        "first_odometer": 1000.0,
        "last_odometer": 2500.0,
    }

    metrics = [
        "speed",
        "main_battery",
        "alerts",
        "comm_quality",
        "samples",
        "signal",
        "satellites",
        "odometer",
    ]
    point = _map_row_to_point(row, metrics)

    assert point.bucket == bucket
    assert point.speed.avg_speed == 40.0
    assert point.main_battery.avg_voltage == 12.0
    assert point.backup_battery.avg_voltage is None
    assert point.alerts.count == 3
    assert point.comm_quality.count_comm_fixable == 1
    assert point.samples.total == 100
    assert point.odometer.total_distance_mt == 1500.0


def test_map_row_to_point_odometer_none_when_partial():
    row = MagicMock()
    row._mapping = {
        "bucket": datetime.now(timezone.utc),
        "first_odometer": None,
        "last_odometer": 100.0,
    }
    point = _map_row_to_point(row, ["odometer"])
    assert point.odometer.total_distance_mt is None


def test_group_rows_by_device_preserves_order_and_skips_unknown():
    dev_ids = ["a", "b"]
    metrics = ["speed"]

    r1 = MagicMock()
    r1._mapping = {
        "device_id": "a",
        "bucket": datetime.now(timezone.utc),
        "avg_speed": 1.0,
        "min_speed": 1.0,
        "max_speed": 2.0,
    }
    r_unknown = MagicMock()
    r_unknown._mapping = {
        "device_id": "ghost",
        "bucket": datetime.now(timezone.utc),
        "avg_speed": 9.0,
        "min_speed": 9.0,
        "max_speed": 9.0,
    }

    grouped = _group_rows_by_device([r1, r_unknown], dev_ids, metrics)
    assert list(grouped.keys()) == ["a", "b"]
    assert len(grouped["a"]) == 1
    assert grouped["b"] == []


def test_validate_device_access_raises_when_not_in_list(monkeypatch):
    monkeypatch.setattr(tel_mod, "_get_accessible_device_ids", lambda db, user: ["x"])

    user = MagicMock(spec=User)
    db = MagicMock()

    with pytest.raises(HTTPException) as ei:
        validate_device_access(db, user, "y")
    assert ei.value.status_code == 404


def test_validate_batch_device_access_raises_when_not_subset(monkeypatch):
    monkeypatch.setattr(tel_mod, "_get_accessible_device_ids", lambda db, user: ["a"])

    user = MagicMock(spec=User)
    db = MagicMock()

    with pytest.raises(HTTPException) as ei:
        validate_batch_device_access(db, user, ["a", "b"])
    assert "no encontrados" in ei.value.detail

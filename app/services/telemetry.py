"""
Servicio de Telemetría Agregada.

Responsabilidades:
  1. Validar que el usuario tenga acceso a los dispositivos solicitados.
  2. Construir y ejecutar queries SQL parametrizadas sobre telemetry_hourly_stats.
  3. Mapear filas de DB a schemas semánticos sin exponer sum_* ni count_*.

La tabla telemetry_hourly_stats tiene PRIMARY KEY (device_id, bucket) y un índice
compuesto que hace eficientes los filtros por (device_id, bucket) en ese orden.

Rango semiabierto: [from_ts, to_ts) para evitar doble conteo en consultas contiguas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.models.user import User
from app.models.user_unit import UserUnit
from app.schemas.telemetry import (
    AlertsOut,
    BatteryOut,
    CommQualityOut,
    Granularity,
    MetricName,
    SamplesOut,
    SpeedOut,
    TelemetryDeviceItemOut,
    TelemetryPointOut,
)

# ---------------------------------------------------------------------------
# Control de acceso
# ---------------------------------------------------------------------------


def _get_accessible_device_ids(db: Session, user: User) -> List[str]:
    """
    Retorna device_ids accesibles para el usuario.

    Regla:
      - is_master=True  → todos los devices de la organización (via units activas)
      - is_master=False → solo devices vinculados a units visibles en user_units
    """
    if user.is_master:
        # Master: todos los devices vinculados a units de la organización
        rows = (
            db.query(UnitDevice.device_id)
            .join(Unit, Unit.id == UnitDevice.unit_id)
            .filter(
                Unit.organization_id == user.organization_id,
                Unit.deleted_at.is_(None),
            )
            .distinct()
            .all()
        )
    else:
        # Usuario normal: solo devices vinculados a units asignadas vía user_units
        accessible_unit_ids = (
            db.query(UserUnit.unit_id)
            .join(Unit, Unit.id == UserUnit.unit_id)
            .filter(
                UserUnit.user_id == user.id,
                Unit.organization_id == user.organization_id,
                Unit.deleted_at.is_(None),
            )
            .subquery()
        )
        rows = (
            db.query(UnitDevice.device_id)
            .filter(UnitDevice.unit_id.in_(accessible_unit_ids))
            .distinct()
            .all()
        )

    return [r[0] for r in rows]


def validate_device_access(db: Session, user: User, device_id: str) -> None:
    """
    Lanza HTTPException 404 si el usuario no tiene acceso al dispositivo.
    Se usa 404 (en lugar de 403) para no filtrar existencia.
    """
    accessible = _get_accessible_device_ids(db, user)
    if device_id not in accessible:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispositivo no encontrado",
        )


def validate_batch_device_access(
    db: Session, user: User, device_ids: Sequence[str]
) -> None:
    """
    Valida en una sola consulta que todos los device_ids estén accesibles.
    Si alguno falta, responde 404 genérico sin filtrar cuál es el problemático.
    """
    accessible = set(_get_accessible_device_ids(db, user))
    requested = set(device_ids)
    if not requested.issubset(accessible):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uno o más dispositivos no encontrados",
        )


# ---------------------------------------------------------------------------
# Construcción de SELECT dinámico
# ---------------------------------------------------------------------------


def _build_select_columns(metrics: Sequence[MetricName], prefix: str = "") -> str:
    """
    Construye los fragmentos SELECT calculados según las métricas pedidas.
    Para granularity=day se espera que prefix='SUM' y se pase con el grupo correcto.
    Este método devuelve solo las columnas de métricas, sin bucket ni device_id.
    """
    cols: List[str] = []

    if "speed" in metrics:
        cols += [
            "SUM(sum_speed) / NULLIF(SUM(count_speed), 0) AS avg_speed",
            "MAX(max_speed) AS max_speed",
        ]

    if "main_battery" in metrics:
        cols += [
            "SUM(sum_main_voltage) / NULLIF(SUM(count_main_voltage), 0) AS avg_main_voltage",
            "MIN(min_main_voltage) AS min_main_voltage",
        ]

    if "backup_battery" in metrics:
        cols += [
            "SUM(sum_backup_voltage) / NULLIF(SUM(count_backup_voltage), 0) AS avg_backup_voltage",
            "MIN(min_backup_voltage) AS min_backup_voltage",
        ]

    if "alerts" in metrics:
        cols.append("SUM(count_alerts) AS count_alerts")

    if "comm_quality" in metrics:
        cols += [
            "SUM(count_comm_fixable) AS count_comm_fixable",
            "SUM(count_comm_with_fix) AS count_comm_with_fix",
        ]

    if "samples" in metrics:
        cols.append("SUM(samples) AS samples")

    return ",\n    ".join(cols)


# ---------------------------------------------------------------------------
# Queries por dispositivo único
# ---------------------------------------------------------------------------


def _query_single_hour(
    db: Session,
    device_id: str,
    from_ts: datetime,
    to_ts: datetime,
    metrics: Sequence[MetricName],
) -> List[TelemetryPointOut]:
    """Query para granularity=hour sobre un único dispositivo."""
    metric_cols = _build_select_columns(metrics)
    if not metric_cols:
        return []

    sql = text(
        f"""
        SELECT
            bucket,
            {metric_cols}
        FROM telemetry_hourly_stats
        WHERE device_id = :device_id
          AND bucket >= :from_ts
          AND bucket < :to_ts
        GROUP BY bucket
        ORDER BY bucket ASC
        """
    )

    rows = db.execute(
        sql,
        {"device_id": device_id, "from_ts": from_ts, "to_ts": to_ts},
    ).fetchall()

    return [_map_row_to_point(row, metrics) for row in rows]


def _query_single_day(
    db: Session,
    device_id: str,
    from_ts: datetime,
    to_ts: datetime,
    metrics: Sequence[MetricName],
) -> List[TelemetryPointOut]:
    """Query para granularity=day sobre un único dispositivo."""
    metric_cols = _build_select_columns(metrics)
    if not metric_cols:
        return []

    sql = text(
        f"""
        SELECT
            date_trunc('day', bucket) AS bucket,
            {metric_cols}
        FROM telemetry_hourly_stats
        WHERE device_id = :device_id
          AND bucket >= :from_ts
          AND bucket < :to_ts
        GROUP BY date_trunc('day', bucket)
        ORDER BY bucket ASC
        """
    )

    rows = db.execute(
        sql,
        {"device_id": device_id, "from_ts": from_ts, "to_ts": to_ts},
    ).fetchall()

    return [_map_row_to_point(row, metrics) for row in rows]


# ---------------------------------------------------------------------------
# Queries multi-dispositivo
# ---------------------------------------------------------------------------


def _query_multi_hour(
    db: Session,
    device_ids: Sequence[str],
    from_ts: datetime,
    to_ts: datetime,
    metrics: Sequence[MetricName],
) -> Dict[str, List[TelemetryPointOut]]:
    """Query batch para granularity=hour."""
    metric_cols = _build_select_columns(metrics)
    if not metric_cols:
        return {d: [] for d in device_ids}

    # Usar ANY con array de PostgreSQL para IN eficiente
    sql = text(
        f"""
        SELECT
            device_id,
            bucket,
            {metric_cols}
        FROM telemetry_hourly_stats
        WHERE device_id = ANY(:device_ids)
          AND bucket >= :from_ts
          AND bucket < :to_ts
        ORDER BY device_id ASC, bucket ASC
        """
    )

    rows = db.execute(
        sql,
        {"device_ids": list(device_ids), "from_ts": from_ts, "to_ts": to_ts},
    ).fetchall()

    return _group_rows_by_device(rows, device_ids, metrics)


def _query_multi_day(
    db: Session,
    device_ids: Sequence[str],
    from_ts: datetime,
    to_ts: datetime,
    metrics: Sequence[MetricName],
) -> Dict[str, List[TelemetryPointOut]]:
    """Query batch para granularity=day."""
    metric_cols = _build_select_columns(metrics)
    if not metric_cols:
        return {d: [] for d in device_ids}

    sql = text(
        f"""
        SELECT
            device_id,
            date_trunc('day', bucket) AS bucket,
            {metric_cols}
        FROM telemetry_hourly_stats
        WHERE device_id = ANY(:device_ids)
          AND bucket >= :from_ts
          AND bucket < :to_ts
        GROUP BY device_id, date_trunc('day', bucket)
        ORDER BY device_id ASC, bucket ASC
        """
    )

    rows = db.execute(
        sql,
        {"device_ids": list(device_ids), "from_ts": from_ts, "to_ts": to_ts},
    ).fetchall()

    return _group_rows_by_device(rows, device_ids, metrics)


# ---------------------------------------------------------------------------
# Mapeo de filas a schemas semánticos
# ---------------------------------------------------------------------------


def _map_row_to_point(row, metrics: Sequence[MetricName]) -> TelemetryPointOut:
    """
    Convierte una fila de resultado SQL a TelemetryPointOut.
    Los campos de métricas no pedidas quedan como None (excluídos en la respuesta
    con response_model_exclude_none=True en el endpoint).
    """
    mapping = row._mapping

    speed_out: Optional[SpeedOut] = None
    main_battery_out: Optional[BatteryOut] = None
    backup_battery_out: Optional[BatteryOut] = None
    alerts_out: Optional[AlertsOut] = None
    comm_out: Optional[CommQualityOut] = None
    samples_out: Optional[SamplesOut] = None

    if "speed" in metrics:
        speed_out = SpeedOut(
            avg_speed=mapping.get("avg_speed"),
            max_speed=mapping.get("max_speed"),
        )

    if "main_battery" in metrics:
        main_battery_out = BatteryOut(
            avg_voltage=mapping.get("avg_main_voltage"),
            min_voltage=mapping.get("min_main_voltage"),
        )

    if "backup_battery" in metrics:
        backup_battery_out = BatteryOut(
            avg_voltage=mapping.get("avg_backup_voltage"),
            min_voltage=mapping.get("min_backup_voltage"),
        )

    if "alerts" in metrics:
        alerts_out = AlertsOut(count=mapping.get("count_alerts") or 0)

    if "comm_quality" in metrics:
        comm_out = CommQualityOut(
            fixable_count=mapping.get("count_comm_fixable") or 0,
            with_fix_count=mapping.get("count_comm_with_fix") or 0,
        )

    if "samples" in metrics:
        samples_out = SamplesOut(total=mapping.get("samples") or 0)

    return TelemetryPointOut(
        bucket=mapping["bucket"],
        speed=speed_out,
        main_battery=main_battery_out,
        backup_battery=backup_battery_out,
        alerts=alerts_out,
        comm_quality=comm_out,
        samples=samples_out,
    )


def _group_rows_by_device(
    rows,
    device_ids: Sequence[str],
    metrics: Sequence[MetricName],
) -> Dict[str, List[TelemetryPointOut]]:
    """Agrupa filas por device_id, preservando orden original de device_ids."""
    result: Dict[str, List[TelemetryPointOut]] = {d: [] for d in device_ids}
    for row in rows:
        dev_id = row._mapping["device_id"]
        if dev_id in result:
            result[dev_id].append(_map_row_to_point(row, metrics))
    return result


# ---------------------------------------------------------------------------
# API pública del servicio
# ---------------------------------------------------------------------------


def get_telemetry_single(
    db: Session,
    user: User,
    device_id: str,
    from_ts: datetime,
    to_ts: datetime,
    granularity: Granularity,
    metrics: List[MetricName],
) -> List[TelemetryPointOut]:
    """
    Retorna la serie temporal de telemetría para un dispositivo.
    Valida acceso antes de ejecutar la query.
    """
    validate_device_access(db, user, device_id)

    if granularity == "hour":
        return _query_single_hour(db, device_id, from_ts, to_ts, metrics)
    else:
        return _query_single_day(db, device_id, from_ts, to_ts, metrics)


def get_telemetry_batch(
    db: Session,
    user: User,
    device_ids: List[str],
    from_ts: datetime,
    to_ts: datetime,
    granularity: Granularity,
    metrics: List[MetricName],
) -> List[TelemetryDeviceItemOut]:
    """
    Retorna la serie temporal agrupada por dispositivo.
    Valida acceso a todos los device_ids en una sola consulta.
    """
    validate_batch_device_access(db, user, device_ids)

    if granularity == "hour":
        grouped = _query_multi_hour(db, device_ids, from_ts, to_ts, metrics)
    else:
        grouped = _query_multi_day(db, device_ids, from_ts, to_ts, metrics)

    # Preservar orden original del request
    return [
        TelemetryDeviceItemOut(device_id=dev_id, series=grouped[dev_id])
        for dev_id in device_ids
    ]

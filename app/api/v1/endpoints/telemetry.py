"""
Endpoints de Telemetría Agregada.

Expone métricas semánticas calculadas a partir de telemetry_hourly_stats.
La lógica de queries y acceso reside en app.services.telemetry.

Endpoints:
  GET  /devices/{device_id}/telemetry  → serie temporal por dispositivo
  POST /telemetry/query                → consulta batch multi-dispositivo
"""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full
from app.db.session import get_db
from app.models.user import User
from app.schemas.telemetry import (
    MAX_RANGE_DAYS,
    MAX_RANGE_HOURS,
    VALID_METRICS,
    Granularity,
    MetricName,
    TelemetryMultiDeviceResponse,
    TelemetryQueryRequest,
    TelemetrySingleDeviceResponse,
)
from app.services.telemetry import get_telemetry_batch, get_telemetry_single

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /devices/{device_id}/telemetry
# ---------------------------------------------------------------------------


@router.get(
    "/devices/{device_id}/telemetry",
    response_model=TelemetrySingleDeviceResponse,
    response_model_exclude_none=True,
    summary="Telemetría de un dispositivo",
    description=(
        "Retorna la serie temporal de métricas agregadas para un dispositivo GPS. "
        "Solo se incluyen los buckets que tienen datos; no se rellenan períodos vacíos. "
        "El rango es semiabierto: [from, to). "
        "Límites de rango: hour=7 días, day=180 días."
    ),
    tags=["telemetry"],
)
def get_device_telemetry(
    device_id: str,
    from_ts: datetime = Query(
        ...,
        alias="from",
        description="Inicio del rango (inclusivo, timezone-aware, ISO 8601)",
    ),
    to_ts: datetime = Query(
        ...,
        alias="to",
        description="Fin del rango (exclusivo, timezone-aware, ISO 8601)",
    ),
    granularity: Granularity = Query(
        "hour",
        description="Granularidad de agrupación: 'hour' o 'day'",
    ),
    metrics: List[MetricName] = Query(
        default=[],
        description=(
            f"Métricas a incluir. Opciones: {sorted(VALID_METRICS)}. "
            "Se puede repetir el parámetro: ?metrics=speed&metrics=alerts. "
            "Si no se especifica ninguna, retorna 400."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    _validate_single_request(from_ts, to_ts, granularity, metrics)

    # Deduplicar sin cambiar orden
    metrics = _dedup(metrics)

    series = get_telemetry_single(
        db=db,
        user=current_user,
        device_id=device_id,
        from_ts=from_ts,
        to_ts=to_ts,
        granularity=granularity,
        metrics=metrics,
    )

    return TelemetrySingleDeviceResponse(
        device_id=device_id,
        granularity=granularity,
        **{"from": from_ts, "to": to_ts},
        metrics=metrics,
        series=series,
    )


# ---------------------------------------------------------------------------
# POST /telemetry/query
# ---------------------------------------------------------------------------


@router.post(
    "/telemetry/query",
    response_model=TelemetryMultiDeviceResponse,
    response_model_exclude_none=True,
    summary="Consulta batch de telemetría",
    description=(
        "Permite consultar telemetría de múltiples dispositivos en una sola llamada. "
        "Todos los device_ids deben pertenecer a dispositivos accesibles por el usuario. "
        "Si algún dispositivo no es accesible, retorna 404. "
        "El rango es semiabierto: [from, to). "
        "Límites de rango: hour=7 días, day=180 días."
    ),
    status_code=status.HTTP_200_OK,
    tags=["telemetry"],
)
def query_telemetry_batch(
    body: TelemetryQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    devices = get_telemetry_batch(
        db=db,
        user=current_user,
        device_ids=body.device_ids,
        from_ts=body.from_ts,
        to_ts=body.to_ts,
        granularity=body.granularity,
        metrics=body.metrics,
    )

    return TelemetryMultiDeviceResponse(
        granularity=body.granularity,
        **{"from": body.from_ts, "to": body.to_ts},
        metrics=body.metrics,
        devices=devices,
    )


# ---------------------------------------------------------------------------
# Helpers de validación para el endpoint GET
# ---------------------------------------------------------------------------


def _validate_single_request(
    from_ts: datetime,
    to_ts: datetime,
    granularity: Granularity,
    metrics: List[str],
) -> None:
    if from_ts.tzinfo is None or to_ts.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Los timestamps deben incluir zona horaria (timezone-aware)",
        )

    if from_ts >= to_ts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'from' debe ser anterior a 'to'",
        )

    delta = to_ts - from_ts
    if granularity == "hour" and delta > MAX_RANGE_HOURS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Con granularity=hour el rango máximo es {MAX_RANGE_HOURS.days} días",
        )
    if granularity == "day" and delta > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Con granularity=day el rango máximo es {MAX_RANGE_DAYS.days} días",
        )

    if not metrics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Se debe especificar al menos una métrica",
        )

    invalid = set(metrics) - VALID_METRICS
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Métricas no válidas: {sorted(invalid)}. Opciones: {sorted(VALID_METRICS)}",
        )


def _dedup(values: List) -> List:
    seen = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return seen

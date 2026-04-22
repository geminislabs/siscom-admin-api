"""
Schemas de Telemetría Agregada.

Expone métricas semánticas calculadas a partir de telemetry_hourly_stats.
NO expone sumatorias (sum_*) ni contadores internos (count_*) de la tabla.

Métricas soportadas:
  - speed          → avg_speed, max_speed
  - main_battery   → avg_voltage, min_voltage
  - backup_battery → avg_voltage, min_voltage
  - alerts         → count
  - comm_quality   → fixable_count, with_fix_count
  - samples        → total

Granularidades:
  - hour  → datos por bucket horario tal como están
  - day   → re-agrega por date_trunc('day', bucket)

Límites de rango:
  - hour  → máximo 7 días
  - day   → máximo 180 días
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

VALID_METRICS = frozenset(
    ["speed", "main_battery", "backup_battery", "alerts", "comm_quality", "samples"]
)

MAX_RANGE_HOURS = timedelta(days=7)
MAX_RANGE_DAYS = timedelta(days=180)
MAX_BATCH_DEVICES = 50

Granularity = Literal["hour", "day"]
MetricName = Literal[
    "speed", "main_battery", "backup_battery", "alerts", "comm_quality", "samples"
]


# ---------------------------------------------------------------------------
# Sub-modelos de métricas (output)
# ---------------------------------------------------------------------------


class SpeedOut(BaseModel):
    avg_speed: Optional[float] = Field(None, description="Velocidad promedio (km/h)")
    max_speed: Optional[float] = Field(None, description="Velocidad máxima (km/h)")


class BatteryOut(BaseModel):
    avg_voltage: Optional[float] = Field(None, description="Voltaje promedio (V)")
    min_voltage: Optional[float] = Field(None, description="Voltaje mínimo (V)")


class AlertsOut(BaseModel):
    count: int = Field(..., description="Total de alertas en el período")


class CommQualityOut(BaseModel):
    fixable_count: int = Field(
        ..., description="Mensajes con error recuperable de comunicación"
    )
    with_fix_count: int = Field(
        ..., description="Mensajes que llegaron con corrección aplicada"
    )


class SamplesOut(BaseModel):
    total: int = Field(..., description="Total de mensajes procesados en el período")


# ---------------------------------------------------------------------------
# Punto de serie temporal (output)
# ---------------------------------------------------------------------------


class TelemetryPointOut(BaseModel):
    bucket: datetime = Field(
        ..., description="Inicio del período (ISO 8601, timezone-aware)"
    )
    speed: Optional[SpeedOut] = None
    main_battery: Optional[BatteryOut] = None
    backup_battery: Optional[BatteryOut] = None
    alerts: Optional[AlertsOut] = None
    comm_quality: Optional[CommQualityOut] = None
    samples: Optional[SamplesOut] = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Response para un solo dispositivo
# ---------------------------------------------------------------------------


class TelemetrySingleDeviceResponse(BaseModel):
    device_id: str = Field(..., description="ID del dispositivo consultado")
    granularity: Granularity = Field(..., description="Granularidad aplicada")
    from_ts: datetime = Field(
        ..., alias="from", description="Inicio del rango (inclusivo)"
    )
    to_ts: datetime = Field(..., alias="to", description="Fin del rango (exclusivo)")
    metrics: List[MetricName] = Field(
        ..., description="Métricas incluidas en la respuesta"
    )
    series: List[TelemetryPointOut] = Field(
        ..., description="Serie temporal ordenada por bucket ASC"
    )

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Request batch (POST /telemetry/query)
# ---------------------------------------------------------------------------


class TelemetryQueryRequest(BaseModel):
    device_ids: List[str] = Field(
        ...,
        min_length=1,
        description=f"IDs de dispositivos a consultar (máximo {MAX_BATCH_DEVICES})",
    )
    from_ts: datetime = Field(
        ..., alias="from", description="Inicio del rango (inclusivo, timezone-aware)"
    )
    to_ts: datetime = Field(
        ..., alias="to", description="Fin del rango (exclusivo, timezone-aware)"
    )
    granularity: Granularity = Field("hour", description="Granularidad de agrupación")
    metrics: List[MetricName] = Field(
        ..., min_length=1, description="Métricas a incluir en la respuesta"
    )

    model_config = {"populate_by_name": True}

    @field_validator("device_ids")
    @classmethod
    def validate_device_ids(cls, v: List[str]) -> List[str]:
        if len(v) > MAX_BATCH_DEVICES:
            raise ValueError(
                f"Se permiten máximo {MAX_BATCH_DEVICES} dispositivos por consulta"
            )
        # Deduplicar manteniendo orden
        seen = []
        for d in v:
            if d not in seen:
                seen.append(d)
        return seen

    @field_validator("metrics")
    @classmethod
    def validate_metrics(cls, v: List[str]) -> List[str]:
        invalid = set(v) - VALID_METRICS
        if invalid:
            raise ValueError(
                f"Métricas no válidas: {sorted(invalid)}. "
                f"Opciones: {sorted(VALID_METRICS)}"
            )
        # Deduplicar manteniendo orden
        seen = []
        for m in v:
            if m not in seen:
                seen.append(m)
        return seen

    @field_validator("from_ts", "to_ts", mode="before")
    @classmethod
    def ensure_timezone_aware(cls, v):
        if isinstance(v, str):
            # Pydantic parsea el string; si llega como datetime ya parseado lo validamos abajo
            return v
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError(
                "Los timestamps deben incluir zona horaria (timezone-aware)"
            )
        return v

    @model_validator(mode="after")
    def validate_range(self) -> "TelemetryQueryRequest":
        from_ts = self.from_ts
        to_ts = self.to_ts

        # Asegurar timezone-aware
        if from_ts.tzinfo is None:
            raise ValueError("'from' debe ser timezone-aware")
        if to_ts.tzinfo is None:
            raise ValueError("'to' debe ser timezone-aware")

        if from_ts >= to_ts:
            raise ValueError("'from' debe ser anterior a 'to'")

        delta = to_ts - from_ts
        if self.granularity == "hour" and delta > MAX_RANGE_HOURS:
            raise ValueError(
                f"Con granularity=hour el rango máximo es {MAX_RANGE_HOURS.days} días"
            )
        if self.granularity == "day" and delta > MAX_RANGE_DAYS:
            raise ValueError(
                f"Con granularity=day el rango máximo es {MAX_RANGE_DAYS.days} días"
            )

        return self


# ---------------------------------------------------------------------------
# Response batch
# ---------------------------------------------------------------------------


class TelemetryDeviceItemOut(BaseModel):
    device_id: str = Field(..., description="ID del dispositivo")
    series: List[TelemetryPointOut] = Field(
        ..., description="Serie temporal ordenada por bucket ASC"
    )


class TelemetryMultiDeviceResponse(BaseModel):
    granularity: Granularity = Field(..., description="Granularidad aplicada")
    from_ts: datetime = Field(
        ..., alias="from", description="Inicio del rango (inclusivo)"
    )
    to_ts: datetime = Field(..., alias="to", description="Fin del rango (exclusivo)")
    metrics: List[MetricName] = Field(..., description="Métricas incluidas")
    devices: List[TelemetryDeviceItemOut] = Field(
        ..., description="Resultados por dispositivo"
    )

    model_config = {"populate_by_name": True}

"""Bootstrap OpenTelemetry. Idempotente. Sin endpoint = no-op."""

from __future__ import annotations

import socket
from typing import Any, Optional

from opentelemetry import metrics, trace
from opentelemetry.propagate import set_global_textmap
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

tracer_provider: Optional[Any] = None
meter_provider: Optional[Any] = None
logger_provider: Optional[Any] = None

_started = False
_enabled = False


def telemetry_enabled() -> bool:
    return _enabled


def get_tracer_provider() -> Optional[Any]:
    return tracer_provider


def get_meter_provider() -> Optional[Any]:
    return meter_provider


def get_logger_provider() -> Optional[Any]:
    return logger_provider


def _otlp_base(endpoint: str) -> str:
    return endpoint.rstrip("/")


def setup_telemetry(settings: Any) -> None:
    """Registra providers OTel. Segunda llamada no-op. Endpoint vacío = silencio."""
    global tracer_provider, meter_provider, logger_provider, _started, _enabled

    if _started:
        return

    endpoint = (getattr(settings, "OTLP_ENDPOINT", None) or "").strip()
    if not endpoint:
        _started = True
        _enabled = False
        return

    import logging

    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": getattr(settings, "SERVICE_NAME", "siscom-admin-api"),
            "service.version": getattr(settings, "SERVICE_VERSION", "unknown"),
            "deployment.environment": getattr(settings, "DEPLOY_ENV", "local"),
            "host.name": socket.gethostname(),
        }
    )
    base = _otlp_base(endpoint)

    tp = TracerProvider(resource=resource)
    tp.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{base}/v1/traces"))
    )
    trace.set_tracer_provider(tp)
    set_global_textmap(TraceContextTextMapPropagator())

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{base}/v1/metrics"),
        export_interval_millis=30_000,
    )
    mp = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(mp)

    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{base}/v1/logs"))
    )
    logging.getLogger().addHandler(
        LoggingHandler(level=logging.NOTSET, logger_provider=lp)
    )

    tracer_provider = tp
    meter_provider = mp
    logger_provider = lp
    _started = True
    _enabled = True


def instrument_app(app: Any) -> None:
    """Instrumentors automáticos. No-op si no hay Collector."""
    if not _enabled:
        return

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    from app.db.session import engine

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        excluded_urls="health,metrics",
    )
    SQLAlchemyInstrumentor().instrument(
        engine=engine,
        tracer_provider=tracer_provider,
        enable_commenter=True,
        capture_parameters=False,
    )
    HTTPXClientInstrumentor().instrument(tracer_provider=tracer_provider)
    RequestsInstrumentor().instrument(tracer_provider=tracer_provider)


def reset_telemetry_for_tests() -> None:
    """Solo tests: permite volver a llamar setup_telemetry."""
    global tracer_provider, meter_provider, logger_provider, _started, _enabled
    tracer_provider = None
    meter_provider = None
    logger_provider = None
    _started = False
    _enabled = False

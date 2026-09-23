"""Observabilidad operacional (OpenTelemetry). Sin PII."""

from app.observability.init import (
    get_logger_provider,
    get_meter_provider,
    get_tracer_provider,
    reset_telemetry_for_tests,
    setup_telemetry,
    telemetry_enabled,
)
from app.observability.logging import configure_json_logging
from app.observability.metrics import (
    record_api_error,
    record_auth_attempt,
    record_session_delta,
)

__all__ = [
    "configure_json_logging",
    "get_logger_provider",
    "get_meter_provider",
    "get_tracer_provider",
    "record_api_error",
    "record_auth_attempt",
    "record_session_delta",
    "reset_telemetry_for_tests",
    "setup_telemetry",
    "telemetry_enabled",
]

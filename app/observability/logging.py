"""JSON formatter estructurado: única fuente del root logger."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from opentelemetry import trace

from app.observability.request_id import current_request_id

SCRUB_KEY_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "card_number",
    "cvv",
    "ssn",
    "curp",
    "rfc",
    "access_token",
    "refresh_token",
    "private_key",
)

REDACTED = "[REDACTED]"

_RECORD_SKIP = {
    "name",
    "msg",
    "args",
    "created",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "exc_info",
    "exc_text",
    "thread",
    "threadName",
    "message",
    "taskName",
    "asctime",
    "extra_data",
}

_logging_configured = False


def _key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in SCRUB_KEY_FRAGMENTS)


def scrub_value(key: str, value: Any) -> Any:
    if _key_is_sensitive(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: scrub_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_value(key, item) for item in value]
    return value


def _active_trace_ids() -> tuple[str, str]:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return "", ""
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


class JSONFormatter(logging.Formatter):
    """Formatter JSON con trace_id, scrubber y campos de servicio."""

    def __init__(
        self,
        service_name: str = "siscom-admin-api",
        deploy_env: str = "local",
    ) -> None:
        super().__init__()
        self.service_name = service_name
        self.deploy_env = deploy_env

    def format(self, record: logging.LogRecord) -> str:
        trace_id, span_id = _active_trace_ids()
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service.name": self.service_name,
            "deployment.environment": self.deploy_env,
            "trace_id": trace_id,
            "span_id": span_id,
            "request_id": current_request_id(),
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_data["extra"] = scrub_value("extra", record.extra_data)

        for key, value in record.__dict__.items():
            if key in _RECORD_SKIP or key.startswith("_"):
                continue
            log_data[key] = scrub_value(key, value)

        return json.dumps(log_data, ensure_ascii=False, default=str)


class HealthCheckFilter(logging.Filter):
    """Suprime los logs de acceso del endpoint /health cuando son exitosos."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.access" and isinstance(record.args, tuple):
            if len(record.args) >= 3:
                path = str(record.args[2]).split("?", 1)[0]
                if path == "/health":
                    return False

        message = record.getMessage()
        if " /health" in message and "HTTP/" in message:
            return False

        return True


def configure_json_logging(settings: Any, level: Optional[str] = None) -> None:
    """Configura el root logger. Idempotente."""
    global _logging_configured
    if _logging_configured and level is None:
        return

    deploy_env = getattr(settings, "DEPLOY_ENV", "local") or "local"
    raw_level = (level or getattr(settings, "LOG_LEVEL", "INFO") or "INFO").upper()
    if deploy_env != "local" and raw_level == "DEBUG":
        raw_level = "INFO"

    numeric = getattr(logging, raw_level, logging.INFO)
    service_name = getattr(settings, "SERVICE_NAME", "siscom-admin-api")

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JSONFormatter(service_name=service_name, deploy_env=deploy_env)
    )
    root_logger.addHandler(handler)

    logging.getLogger("uvicorn").setLevel(logging.INFO)
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.setLevel(logging.INFO)
    uvicorn_access.addFilter(HealthCheckFilter())
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    _logging_configured = True


def reset_logging_for_tests() -> None:
    global _logging_configured
    _logging_configured = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

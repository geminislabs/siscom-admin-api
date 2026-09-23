"""Compat: delega en app.observability.logging."""

from app.core.config import settings
from app.observability.logging import (
    HealthCheckFilter,
    JSONFormatter,
    configure_json_logging,
    get_logger,
)


def setup_logging(level: str = settings.LOG_LEVEL) -> None:
    configure_json_logging(settings, level=level)


__all__ = [
    "HealthCheckFilter",
    "JSONFormatter",
    "configure_json_logging",
    "get_logger",
    "setup_logging",
]

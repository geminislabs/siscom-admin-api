"""Métricas de negocio. Fail-open. No duplica RED HTTP."""

from __future__ import annotations

from opentelemetry import metrics

_counters: dict = {}


def _get(name: str, kind: str, description: str):
    """Lazy: crea el instrumento la primera vez que se invoca, cuando el
    MeterProvider ya está registrado por setup_telemetry()."""
    if name not in _counters:
        meter = metrics.get_meter("siscom-admin-api")
        if kind == "updown":
            _counters[name] = meter.create_up_down_counter(
                name, description=description
            )
        else:
            _counters[name] = meter.create_counter(name, description=description)
    return _counters[name]


def record_auth_attempt(method: str, outcome: str) -> None:
    try:
        _get(
            "auth_attempts_total",
            "counter",
            "Intentos de autenticación resueltos",
        ).add(1, {"method": method, "outcome": outcome})
    except Exception:
        pass


def record_session_delta(delta: int) -> None:
    try:
        _get(
            "active_sessions_total",
            "updown",
            "Sesiones activas aproximadas (login +1 / logout -1)",
        ).add(delta)
    except Exception:
        pass


def record_api_error(endpoint: str, error_type: str) -> None:
    try:
        _get(
            "api_errors_total",
            "counter",
            "Errores no manejados de la API",
        ).add(1, {"endpoint": endpoint, "error_type": error_type})
    except Exception:
        pass

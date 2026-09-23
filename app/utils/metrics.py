"""
Módulo de métricas (stub).
Las métricas de negocio viven en app.observability.metrics.
"""

import logging
import time
from functools import wraps
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def increment_counter(
    metric_name: str,
    value: int = 1,
    tags: Optional[Dict[str, str]] = None,
) -> None:
    """
    Incrementa un contador de métrica (stub).

    Args:
        metric_name: Nombre de la métrica
        value: Valor a incrementar (default: 1)
        tags: Tags adicionales para la métrica
    """
    # TODO: Implementar envío a StatsD/Telegraf
    logger.debug(
        "metrics.counter.stub",
        extra={"metric_name": metric_name, "value": value},
    )


def record_timing(
    metric_name: str,
    duration_ms: float,
    tags: Optional[Dict[str, str]] = None,
) -> None:
    """
    Registra una métrica de tiempo (stub).

    Args:
        metric_name: Nombre de la métrica
        duration_ms: Duración en milisegundos
        tags: Tags adicionales para la métrica
    """
    # TODO: Implementar envío a StatsD/Telegraf
    logger.debug(
        "metrics.timing.stub",
        extra={"metric_name": metric_name, "duration_ms": duration_ms},
    )


def record_gauge(
    metric_name: str,
    value: float,
    tags: Optional[Dict[str, str]] = None,
) -> None:
    """
    Registra un gauge (valor instantáneo) (stub).

    Args:
        metric_name: Nombre de la métrica
        value: Valor del gauge
        tags: Tags adicionales para la métrica
    """
    # TODO: Implementar envío a StatsD/Telegraf
    logger.debug(
        "metrics.gauge.stub",
        extra={"metric_name": metric_name, "value": value},
    )


def time_function(metric_name: Optional[str] = None):
    """
    Decorador para medir el tiempo de ejecución de una función.

    Args:
        metric_name: Nombre de la métrica (usa el nombre de la función si no se proporciona)

    Returns:
        Función decorada
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            duration_ms = (time.time() - start) * 1000

            name = metric_name or f"function.{func.__name__}.duration"
            record_timing(name, duration_ms)

            return result

        return wrapper

    return decorator

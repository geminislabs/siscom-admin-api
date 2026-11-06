"""
Qué tiene que hacer una app móvil con su versión: nada, avisar o actualizar.

Lo decide el servidor (D2 del plan de data token y versiones) leyendo
`client_version_policy`. Lo usan `GET /api/v1/client-config` y, más adelante,
el middleware que responde 426 a las versiones obligadas a actualizar.

Dos reglas que no son incidentales:

- La comparación es **numérica por segmentos**: `1.10.0 > 1.9.0`. Comparar
  cadenas diría lo contrario.
- Una versión **ilegible no bloquea**: devuelve `none`. Dejar sin app a alguien
  por un error de parseo es peor que no avisarle de una actualización.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

PLATAFORMAS = ("ios", "android")

# `1.2.0`, `1.2`, `1.2.0-beta.1`, `1.2.0+45`: sólo cuenta la parte numérica.
_VERSION = re.compile(r"^\s*v?(\d+(?:\.\d+)*)(?:[-+].*)?\s*$")


class Actualizacion(str, Enum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


def parse_version(valor: Optional[str]) -> Optional[Tuple[int, ...]]:
    """`"1.10.0"` → `(1, 10, 0)`, o None si no se puede leer."""
    if not valor:
        return None
    m = _VERSION.match(valor)
    if m is None:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def _comparar(a: Tuple[int, ...], b: Tuple[int, ...]) -> int:
    """-1, 0 o 1. `1.2` y `1.2.0` son la misma versión."""
    largo = max(len(a), len(b))
    a = a + (0,) * (largo - len(a))
    b = b + (0,) * (largo - len(b))
    return (a > b) - (a < b)


def _menor_que(version: Tuple[int, ...], umbral: Optional[str], campo: str) -> bool:
    if umbral is None:
        return False
    limite = parse_version(umbral)
    if limite is None:
        # Dato mal escrito en la tabla: se ignora en vez de bloquear a todos.
        logger.warning(
            "client_version_policy.umbral_ilegible",
            extra={"extra_data": {"campo": campo, "valor": umbral}},
        )
        return False
    return _comparar(version, limite) < 0


def evaluar(
    version: Optional[str],
    *,
    min_supported_version: Optional[str],
    latest_version: Optional[str],
    blocked_versions: Sequence[str] = (),
) -> Actualizacion:
    """Qué corresponde a `version` según una fila de la política."""
    actual = parse_version(version)
    if actual is None:
        return Actualizacion.NONE

    bloqueadas = (parse_version(v) for v in blocked_versions or ())
    if any(b is not None and _comparar(actual, b) == 0 for b in bloqueadas):
        return Actualizacion.REQUIRED
    if _menor_que(actual, min_supported_version, "min_supported_version"):
        return Actualizacion.REQUIRED
    if _menor_que(actual, latest_version, "latest_version"):
        return Actualizacion.OPTIONAL
    return Actualizacion.NONE

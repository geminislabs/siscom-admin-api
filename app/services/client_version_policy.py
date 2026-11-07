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
from enum import Enum
from typing import Optional, Sequence, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

PLATAFORMAS = ("ios", "android")

# Una versión real cabe de sobra; más larga es basura y no se procesa.
_LARGO_MAXIMO = 64


class Actualizacion(str, Enum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


def parse_version(valor: Optional[str]) -> Optional[Tuple[int, ...]]:
    """`"1.10.0"` → `(1, 10, 0)`, o None si no se puede leer.

    Acepta `1.2`, `v1.2.0`, `1.2.0-beta.1` y `1.2.0+45`: sólo cuenta la parte
    numérica. Sin expresión regular a propósito: el valor llega del cliente, y
    la que había era polinómica (CodeQL `py/polynomial-redos`).
    """
    if not valor or len(valor) > _LARGO_MAXIMO:
        return None
    texto = valor.strip()
    if texto[:1] in ("v", "V"):
        texto = texto[1:]
    for separador in ("-", "+"):
        texto = texto.split(separador, 1)[0]
    partes = texto.split(".")
    if not all(p.isascii() and p.isdigit() for p in partes):
        return None
    return tuple(int(p) for p in partes)


TIENDAS = {"ios": "apps.apple.com", "android": "play.google.com"}
MAX_BLOQUEADAS = 50


class PoliticaInvalida(ValueError):
    """Una política que no se puede guardar. `campo` dice cuál, para GAC."""

    def __init__(self, detalle: str, campo: Optional[str] = None):
        super().__init__(detalle)
        self.detalle = detalle
        self.campo = campo


def _limpiar(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    valor = valor.strip()
    return valor or None


def validar_politica(
    plataforma: str,
    *,
    min_supported_version: Optional[str],
    latest_version: Optional[str],
    blocked_versions: Sequence[str],
    store_url: Optional[str],
) -> dict:
    """La fila lista para guardar, o `PoliticaInvalida`.

    Aquí sí se rechaza una versión ilegible: en `evaluar` se ignora para no
    bloquear a nadie, pero guardarla dejaría una regla que no hace nada sin
    que nadie se entere.
    """
    minima = _limpiar(min_supported_version)
    ultima = _limpiar(latest_version)
    tienda = _limpiar(store_url)

    for campo, valor in (
        ("min_supported_version", minima),
        ("latest_version", ultima),
    ):
        if valor is not None and parse_version(valor) is None:
            raise PoliticaInvalida(
                f"{campo} no es una versión legible: {valor!r}", campo
            )

    if minima and ultima:
        if _comparar(parse_version(minima), parse_version(ultima)) > 0:
            raise PoliticaInvalida(
                "min_supported_version no puede ser mayor que latest_version",
                "min_supported_version",
            )

    bloqueadas = []
    vistas = []
    for valor in blocked_versions or ():
        limpia = _limpiar(valor)
        version = parse_version(limpia)
        if version is None:
            raise PoliticaInvalida(
                f"blocked_versions tiene una versión ilegible: {valor!r}",
                "blocked_versions",
            )
        if any(_comparar(version, otra) == 0 for otra in vistas):
            raise PoliticaInvalida(
                f"blocked_versions tiene {limpia!r} repetida", "blocked_versions"
            )
        vistas.append(version)
        bloqueadas.append(limpia)
    if len(bloqueadas) > MAX_BLOQUEADAS:
        raise PoliticaInvalida(
            f"blocked_versions admite como máximo {MAX_BLOQUEADAS}",
            "blocked_versions",
        )

    if tienda is not None:
        partes = urlsplit(tienda)
        if partes.scheme != "https" or partes.hostname != TIENDAS[plataforma]:
            raise PoliticaInvalida(
                f"store_url debe ser https://{TIENDAS[plataforma]}/…", "store_url"
            )
    elif minima or bloqueadas:
        # Obligar a actualizar sin decir adónde ir deja al usuario en una
        # pantalla sin salida.
        raise PoliticaInvalida(
            "No se puede obligar a actualizar sin store_url", "store_url"
        )

    return {
        "min_supported_version": minima,
        "latest_version": ultima,
        "blocked_versions": bloqueadas,
        "store_url": tienda,
    }


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

"""
Middleware: 426 a las apps móviles cuya versión ya no se acepta (D2).

`GET /client-config` le dice a la app qué hacer al arrancar; esto lo **hace
cumplir** en cada petición, para la app que no pregunta o que ignora la
respuesta. Sólo actúa si llegan `X-Client-Platform` y `X-Client-Version`: la
web y las apps anteriores a la 1.2.0 no las mandan, y para ellas nada cambia.

Las versiones publicadas ya muestran el `detail` de un 426 en el login
(memoria «forzar actualización en móviles»), así que el mensaje va en el
idioma de `Accept-Language`.

FALLA ABIERTO
=============
Si la política no se puede leer, la petición pasa. Esto no es una barrera de
seguridad —una versión vieja tiene la misma autorización que una nueva—, y
dejar sin app a todo el mundo porque Postgres tardó en responder es peor que
dejar pasar una versión que se quería retirar.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.i18n import t
from app.observability.client_info import client_info_ctx, normalizar
from app.services.client_version_policy import Actualizacion, evaluar

logger = logging.getLogger(__name__)

CACHE_SEGUNDOS = 60

# Lo que una app tiene que poder hacer aunque esté obligada a actualizar:
# preguntar qué hacer, cerrar sesión, y el sondeo del balanceador.
EXENTAS = frozenset(
    {
        f"{settings.API_V1_STR}/client-config",
        f"{settings.API_V1_STR}/auth/logout",
        "/health",
        "/",
    }
)

Politicas = Dict[str, dict]


def _cargar_de_la_base() -> Politicas:
    from app.db.session import SessionLocal
    from app.models.client_version_policy import ClientVersionPolicy

    with SessionLocal() as db:
        return {
            fila.platform: {
                "min_supported_version": fila.min_supported_version,
                "latest_version": fila.latest_version,
                "blocked_versions": list(fila.blocked_versions or ()),
                "store_url": fila.store_url,
            }
            for fila in db.query(ClientVersionPolicy).all()
        }


_cargador: Callable[[], Politicas] = _cargar_de_la_base
_cache: Optional[Politicas] = None
_cargado_en = 0.0
_lock = threading.Lock()


def usar_cargador(cargador: Optional[Callable[[], Politicas]]) -> None:
    """Cambia de dónde sale la política y vacía la caché. Para los tests."""
    global _cargador, _cache
    _cargador = cargador or _cargar_de_la_base
    _cache = None


def invalidar_cache() -> None:
    """Relee la política en la siguiente petición.

    Sólo alcanza a este proceso: los demás workers tardan hasta
    `CACHE_SEGUNDOS`, que es lo que GAC anuncia.
    """
    global _cache
    with _lock:
        _cache = None


def _politicas() -> Optional[Politicas]:
    global _cache, _cargado_en
    ahora = time.monotonic()
    if _cache is not None and ahora - _cargado_en < CACHE_SEGUNDOS:
        return _cache
    with _lock:
        if _cache is not None and ahora - _cargado_en < CACHE_SEGUNDOS:
            return _cache
        try:
            _cache = _cargador()
            _cargado_en = ahora
        except Exception:
            logger.exception("client_version_gate.politica_no_disponible")
            # Se reintenta en la siguiente petición; mientras, se deja pasar.
            return _cache
    return _cache


def _idioma(request: Request) -> str:
    from app.api.deps import get_request_locale

    return get_request_locale(request.headers.get("accept-language"))


async def client_version_gate(request: Request, call_next) -> Response:
    cliente = normalizar(
        request.headers.get("x-client-platform"),
        request.headers.get("x-client-version"),
    )
    token = client_info_ctx.set(cliente)
    try:
        if (
            cliente.platform
            and cliente.version
            and request.url.path not in EXENTAS
            and request.method != "OPTIONS"
        ):
            politica = (_politicas() or {}).get(cliente.platform)
            if politica is not None and (
                evaluar(
                    cliente.version,
                    min_supported_version=politica["min_supported_version"],
                    latest_version=politica["latest_version"],
                    blocked_versions=politica["blocked_versions"],
                )
                is Actualizacion.REQUIRED
            ):
                logger.info("client_version_gate.upgrade_required")
                return JSONResponse(
                    status_code=426,
                    content={
                        "detail": t("client.upgrade_required", _idioma(request)),
                        "error_code": "upgrade_required",
                        "store_url": politica["store_url"],
                    },
                )
        return await call_next(request)
    finally:
        client_info_ctx.reset(token)

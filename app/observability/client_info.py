"""Plataforma y versión de la app que hace la petición, para los logs.

Salen de `X-Client-Platform` y `X-Client-Version`, que mandan las apps móviles
desde la 1.2.0. La web no las manda. Lo eligen los clientes, así que como el
`request_id` se acota antes de llegar al log: un valor que no encaja se
descarta entero.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

PLATAFORMAS = ("ios", "android")
_VERSION_VALIDA = re.compile(r"\A[0-9A-Za-z.+-]{1,32}\Z")


@dataclass(frozen=True)
class ClientInfo:
    platform: Optional[str] = None
    version: Optional[str] = None


_SIN_CLIENTE = ClientInfo()
client_info_ctx: ContextVar[Optional[ClientInfo]] = ContextVar(
    "client_info", default=None
)


def current_client_info() -> ClientInfo:
    return client_info_ctx.get() or _SIN_CLIENTE


def normalizar(plataforma: Optional[str], version: Optional[str]) -> ClientInfo:
    p = (plataforma or "").strip().lower()
    v = (version or "").strip()
    return ClientInfo(
        platform=p if p in PLATAFORMAS else None,
        version=v if _VERSION_VALIDA.match(v) else None,
    )

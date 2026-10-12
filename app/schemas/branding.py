"""
Contrato del tema de marca, `version: 1` (B4).

Es lo que guardan `tenant_branding.draft` y `tenant_branding.published`, y lo
que leen los correos (`logo_url`, `support_email`, `legal_url`) y
`GET /tenant-config`. Antes de este módulo nadie lo escribía ni lo validaba.

QUÉ ESCRIBE EL PARTNER Y QUÉ NO
===============================
El partner manda su nombre, sus URLs, su correo de soporte y una o dos
semillas de color. `tokens` y `version` los pone el servidor: si vienen en la
petición se ignoran, no se rechazan, para que un cliente pueda reenviar lo que
leyó sin limpiarlo. Cualquier otra clave desconocida es un 422: un `logo_ulr`
mal escrito que se descartara en silencio dejaría al partner sin logo sin
saber por qué.

LAS URLS NO SE DESCARGAN
========================
v1 guarda la URL del logo tal cual y el servidor nunca la pide (D1): si
descargara URLs escritas por un usuario abriría un SSRF. Lo que sí se valida
es lo que el navegador de los usuarios va a pedir: `https://`, sin usuario ni
contraseña, con un nombre de host —no una IP ni `localhost`, que harían que el
navegador de cada usuario apuntara a su propia red— y 2 048 caracteres como
máximo.
"""

import ipaddress
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.services.marca_tema import es_hex

VERSION_DEL_CONTRATO = 1

_LARGO_MAXIMO_URL = 2048


def validar_url_publica(valor: str) -> str:
    """La regla de las URLs del tema. Ver la cabecera del módulo."""
    valor = valor.strip()
    if len(valor) > _LARGO_MAXIMO_URL:
        raise ValueError(f"la URL supera {_LARGO_MAXIMO_URL} caracteres")
    partes = urlsplit(valor)
    if partes.scheme != "https":
        raise ValueError("la URL debe empezar con https://")
    if partes.username is not None or partes.password is not None:
        raise ValueError("la URL no puede llevar usuario ni contraseña")
    host = (partes.hostname or "").rstrip(".")
    if not host or "." not in host:
        raise ValueError("la URL necesita un nombre de dominio")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("la URL no puede apuntar a localhost")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return valor
    raise ValueError("la URL debe usar un nombre de dominio, no una IP")


class Semillas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str = Field(..., description="Color primario de la marca, #rrggbb")
    accent: Optional[str] = Field(
        default=None, description="Color de acento, #rrggbb. Sin él, el primario."
    )

    @field_validator("primary", "accent")
    @classmethod
    def _hex(cls, valor: Optional[str]) -> Optional[str]:
        if valor is None:
            return None
        if not es_hex(valor):
            raise ValueError("el color debe ser hexadecimal de seis dígitos: #rrggbb")
        return valor.lower()


class BrandingDraftIn(BaseModel):
    """Lo que manda la pantalla de marca al guardar el borrador."""

    model_config = ConfigDict(extra="forbid")

    brand_name: str = Field(..., min_length=1, max_length=80)
    logo_url: str
    logo_dark_url: Optional[str] = None
    favicon_url: Optional[str] = None
    support_email: EmailStr
    legal_url: str
    seed: Semillas

    # Los pone el servidor; si vienen, se ignoran (ver la cabecera).
    tokens: Optional[Any] = Field(default=None, exclude=True)
    version: Optional[Any] = Field(default=None, exclude=True)

    @field_validator("brand_name")
    @classmethod
    def _nombre(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor:
            raise ValueError("el nombre de la marca no puede estar vacío")
        return valor

    @field_validator("logo_url", "logo_dark_url", "favicon_url", "legal_url")
    @classmethod
    def _url(cls, valor: Optional[str]) -> Optional[str]:
        return None if valor is None else validar_url_publica(valor)


class BrandingOut(BaseModel):
    """Lo que ve la pantalla de marca: el borrador y lo publicado."""

    account_id: UUID
    brand_name: Optional[str] = Field(
        default=None, description="El nombre publicado, el que ven los usuarios"
    )
    draft: Optional[dict[str, Any]] = Field(
        default=None,
        description="El borrador, con su brand_name y los tokens ya derivados",
    )
    published: dict[str, Any] = Field(default_factory=dict)
    published_at: Optional[datetime] = None
    published_by: Optional[UUID] = None


class BrandingDraftOut(BrandingOut):
    """El resultado de guardar: además, cada par comprobado y cada ajuste."""

    contrast: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Cada par texto/fondo comprobado, con su ratio y su mínimo",
    )
    adjustments: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Las semillas que no contrastaban en un modo y el color que se usó "
            "en su lugar"
        ),
    )

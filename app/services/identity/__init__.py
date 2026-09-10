"""
Proveedores de identidad: la interfaz, sus errores y cómo se elige uno.

    from app.services.identity import IdentityProvider, proveedor_para_cuenta

QUIEN ELIGE EL PROVEEDOR
========================
La **cuenta**, nunca una variable de entorno (§9, regla 6 de
`docs/architecture/identidad-y-marca.md`). Si el proveedor fuera global, mover
a un partner enterprise a WorkOS obligaría a mover a todos, que es justo lo que
esta capa existe para evitar.

`accounts.identity_provider` en NULL significa «hereda el del despliegue», que
hoy es Cognito y es el caso de todas las cuentas.

POR QUE UN SINGLETON
====================
El cliente de boto3 es caro de construir y seguro de compartir entre hilos.
Antes se creaba uno por módulo al importarlo, lo que además ataba la
configuración al momento del import.
"""

from typing import TYPE_CHECKING, Optional

from app.services.identity.base import IdentityProvider, Sesion
from app.services.identity.errors import (
    AutenticacionIncompleta,
    CredencialesInvalidas,
    CredencialNoEncontrada,
    CredencialSinConfirmar,
    ErrorDeIdentidad,
    ErrorDelProveedor,
    HandleYaExiste,
    ParametroInvalido,
    PasswordRechazada,
    ProveedorDesconocido,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.account import Account

__all__ = [
    "AutenticacionIncompleta",
    "CredencialNoEncontrada",
    "CredencialSinConfirmar",
    "CredencialesInvalidas",
    "ErrorDeIdentidad",
    "ErrorDelProveedor",
    "HandleYaExiste",
    "IdentityProvider",
    "ParametroInvalido",
    "PasswordRechazada",
    "ProveedorDesconocido",
    "PROVEEDOR_POR_DEFECTO",
    "Sesion",
    "proveedor_para_cuenta",
    "proveedor_por_defecto",
    "reiniciar_proveedores",
]

#: El proveedor de una cuenta que no pide otro. Es también el valor del
#: `server_default` de `users.identity_provider`.
PROVEEDOR_POR_DEFECTO = "cognito"

_instancias: dict[str, IdentityProvider] = {}


def _construir(nombre: str) -> IdentityProvider:
    if nombre == "cognito":
        from app.services.identity.cognito import CognitoIdentityProvider

        return CognitoIdentityProvider()
    raise ProveedorDesconocido(f"proveedor de identidad desconocido: {nombre!r}")


def proveedor(nombre: str) -> IdentityProvider:
    """El proveedor que se llama así, construido una sola vez."""
    if nombre not in _instancias:
        _instancias[nombre] = _construir(nombre)
    return _instancias[nombre]


def proveedor_por_defecto() -> IdentityProvider:
    """El proveedor del despliegue, para quien no tiene cuenta a mano."""
    return proveedor(PROVEEDOR_POR_DEFECTO)


def proveedor_para_cuenta(cuenta: "Optional[Account]") -> IdentityProvider:
    """El proveedor por el que entra esa cuenta.

    Se le pasa la **cuenta de marca** —la dueña de la credencial—, no la cuenta
    del usuario: lo que enruta es por dónde entra, no de quién es cliente. Con
    `None` (la marca por defecto) sale el proveedor del despliegue.
    """
    if cuenta is None or cuenta.identity_provider is None:
        return proveedor_por_defecto()
    return proveedor(cuenta.identity_provider)


def reiniciar_proveedores() -> None:
    """Tira las instancias cacheadas. Para las pruebas, no para producción."""
    _instancias.clear()

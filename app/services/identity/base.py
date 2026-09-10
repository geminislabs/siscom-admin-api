"""
La interfaz `IdentityProvider` y los tipos con los que habla.

QUE ES ESTO
===========
La frontera entre esta aplicación y quien verifica contraseñas. Postgres es la
fuente de verdad de identidad y tenancy (§9 de
`docs/architecture/identidad-y-marca.md`); el proveedor es un verificador de
credenciales y nada más. Esta interfaz es lo que hace que sea intercambiable:
enrutar una marca a WorkOS o a Auth0 debe ser escribir otra implementación, no
reescribir `/auth/login`.

LA REGLA QUE DA SENTIDO AL MODULO
=================================
**Nada de Cognito cruza esta frontera.** Ni `AuthenticationResult`, ni
`ChallengeName`, ni `ClientError`, ni un dict de `UserAttributes`. Lo que entra
y sale son `str`, `Sesion` y las excepciones de `errors.py`. Si algún día hace
falta añadir un parámetro que solo Cognito entiende, la respuesta no es
añadirlo: es que esa decisión no pertenece a esta capa.

EL PROVEEDOR NO TOCA LA BASE
============================
Recibe un **handle** (`users.external_id`) y no un `(marca, correo)`. Resolver
la credencial a partir de la marca y el correo es trabajo de Postgres, y
hacerlo aquí dentro obligaría a cada implementación a conocer el esquema.
El documento de arquitectura §8 esbozaba `authenticate(brand_account_id, email,
password)`; se cambió al escribirlo, y por eso: la marca decide **qué
proveedor** y **qué fila**, las dos cosas antes de llamar. Ver
`proveedor_para_cuenta()` en `__init__.py`.

QUE NO HAY AQUI, Y NO ES UN OLVIDO
==================================
No hay `reset_password_start` / `confirm`. El reinicio de contraseña de este
sistema no pasa por el proveedor: el código lo emite esta aplicación
(`token_confirmacion`), lo envía SES, y lo único que el proveedor hace al final
es `fijar_password`. Declarar dos métodos que nadie implementaría de verdad
habría descrito un sistema que no existe.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Optional


@dataclass(frozen=True)
class Sesion:
    """Lo que devuelve una autenticación correcta.

    Son los tokens del proveedor, ya extraídos de la forma en que vengan. El
    endpoint los copia a su respuesta y no sabe de dónde salieron.
    """

    access_token: str
    id_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: int = 3600


class IdentityProvider(ABC):
    """El contrato que cumple todo proveedor de identidad.

    Los métodos que reciben `handle` reciben `users.external_id`, que es
    **opaco**: correo para los usuarios anteriores a la Fase 3, UUID para los
    que cree la rebanada B2. Ninguna implementación puede parsearlo.
    """

    #: Lo que va en `users.identity_provider` y `accounts.identity_provider`.
    nombre: ClassVar[str]

    # ── Autenticación ────────────────────────────────────────────────
    @abstractmethod
    def autenticar(self, *, handle: str, password: str) -> Sesion:
        """Verifica la contraseña y abre sesión.

        Lanza `CredencialesInvalidas`, `CredencialNoEncontrada`,
        `CredencialSinConfirmar` o `AutenticacionIncompleta`.
        """

    @abstractmethod
    def renovar(self, *, handle: str, refresh_token: str) -> Sesion:
        """Renueva la sesión sin volver a pedir la contraseña.

        El `refresh_token` no se renueva; la `Sesion` que vuelve trae el mismo
        que entró o ninguno, según el proveedor.
        """

    @abstractmethod
    def revocar_sesiones(self, *, access_token: str) -> None:
        """Invalida todas las sesiones del dueño de ese access token."""

    @abstractmethod
    def verificar_token(self, token: str) -> dict:
        """Comprueba la firma de un token de acceso y devuelve sus claims.

        Los claims son datos del proveedor y **se revalidan contra Postgres**
        antes de autorizar nada (§9, regla 1): los atributos del proveedor son
        mutables desde sus APIs de administración.
        """

    # ── Ciclo de vida de la credencial ───────────────────────────────
    @abstractmethod
    def sujeto_de(self, *, handle: str) -> Optional[str]:
        """El sujeto de esa credencial, o `None` si no existe.

        «Sujeto» es lo que el token afirmará (`users.cognito_sub`), que no es
        el handle ni se deduce de él.
        """

    @abstractmethod
    def crear_credencial(
        self,
        *,
        handle: str,
        email: str,
        full_name: Optional[str] = None,
        email_verificado: bool = False,
    ) -> Optional[str]:
        """Da de alta la credencial y devuelve su sujeto.

        No envía correo: el envío es de esta aplicación, por SES y con la
        plantilla de la marca. Lanza `HandleYaExiste` si el handle está tomado.
        """

    @abstractmethod
    def fijar_password(self, *, handle: str, password: str) -> None:
        """Deja la contraseña puesta y utilizable, sin estado intermedio."""

    @abstractmethod
    def marcar_correo_verificado(self, *, handle: str, email: str) -> None:
        """Marca el correo como verificado en el proveedor.

        La verificación de verdad ya ocurrió aquí —el usuario abrió el enlace
        que emitió esta aplicación—; esto solo se lo cuenta al proveedor.
        """

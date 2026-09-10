"""
`CognitoIdentityProvider`: la implementación de `IdentityProvider` sobre AWS.

Es el **único** sitio del repositorio donde debería haber un `boto3.client(
"cognito-idp")`. Antes de esta rebanada había tres —`auth.py`, `users.py` y
`user_commands.py`—, cada uno con su propia traducción de `ClientError` a
`HTTPException`, ligeramente distinta de las otras.

QUE HACE Y QUE NO
=================
Traduce. Entra vocabulario del dominio (handle, contraseña, correo), sale
`Sesion` o una excepción de `errors.py`. Ni un `ClientError` ni un dict de
`UserAttributes` sale de este módulo.

Lo que **no** hace es tocar la base de datos. No sabe qué es una marca, ni una
cuenta, ni una organización: recibe el handle ya resuelto. Ver `base.py`.

EL SECRET_HASH VA SOBRE EL HANDLE
=================================
Cognito lo calcula sobre el `Username`, así que se firma con el mismo handle
con el que se autentica. Firmarlo con el correo mientras se autentica con un
UUID —el error natural cuando lleguen los handles UUID de la rebanada B2— da un
`NotAuthorizedException` indistinguible de una contraseña mal escrita.
"""

import base64
import hashlib
import hmac
import logging
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import HTTPException, status

from app.core.config import settings
from app.services.identity.base import IdentityProvider, Sesion
from app.services.identity.errors import (
    AutenticacionIncompleta,
    CredencialesInvalidas,
    CredencialNoEncontrada,
    CredencialSinConfirmar,
    ErrorDelProveedor,
    HandleYaExiste,
    ParametroInvalido,
    PasswordRechazada,
)

logger = logging.getLogger(__name__)


# El código del error de Cognito -> la clase del dominio. Lo que no esté aquí
# es `ErrorDelProveedor`, que es un 500: un fallo que esta aplicación no sabe
# explicarle a quien llama.
_TRADUCCION = {
    "NotAuthorizedException": CredencialesInvalidas,
    "UserNotFoundException": CredencialNoEncontrada,
    "UserNotConfirmedException": CredencialSinConfirmar,
    "UsernameExistsException": HandleYaExiste,
    "InvalidPasswordException": PasswordRechazada,
    "InvalidParameterException": ParametroInvalido,
}


def construir_cliente_cognito():
    """El cliente de boto3, con la configuración del despliegue.

    `COGNITO_ENDPOINT` existe para apuntar a un doble local; en producción no
    está puesto y boto3 resuelve el endpoint real de la región.
    """
    kwargs: dict[str, Any] = {"region_name": settings.COGNITO_REGION}
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    if getattr(settings, "COGNITO_ENDPOINT", None):
        kwargs["endpoint_url"] = settings.COGNITO_ENDPOINT
    return boto3.client("cognito-idp", **kwargs)


def _traducir(exc: ClientError) -> Exception:
    codigo = exc.response.get("Error", {}).get("Code", "")
    mensaje = exc.response.get("Error", {}).get("Message", str(exc))
    clase = _TRADUCCION.get(codigo, ErrorDelProveedor)
    return clase(mensaje, codigo=codigo)


def _sub_de(atributos: list[dict]) -> Optional[str]:
    """El `sub` dentro de una lista de atributos de Cognito.

    Devuelve `None` si no está, que es la misma respuesta que daba cada uno de
    los tres sitios que hacían este `next(...)` a mano. Quien lo llama decide
    si eso es un error suyo.
    """
    return next(
        (a["Value"] for a in atributos if a["Name"] == "sub"),
        None,
    )


class CognitoIdentityProvider(IdentityProvider):
    """AWS Cognito como verificador de credenciales."""

    nombre = "cognito"

    def __init__(self, cliente=None):
        # Inyectable para las pruebas; en producción se construye solo. El
        # cliente de boto3 es caro de crear y seguro de compartir entre hilos.
        self._cognito = cliente if cliente is not None else construir_cliente_cognito()

    # ── Interno ──────────────────────────────────────────────────────
    def _secret_hash(self, handle: str) -> str:
        mensaje = bytes(handle + settings.COGNITO_CLIENT_ID, "utf-8")
        secreto = bytes(settings.COGNITO_CLIENT_SECRET, "utf-8")
        firma = hmac.new(secreto, msg=mensaje, digestmod=hashlib.sha256).digest()
        return base64.b64encode(firma).decode()

    def _sesion_de(self, respuesta: dict) -> Sesion:
        """Saca los tokens de la respuesta de `initiate_auth`.

        Cuando no hay `AuthenticationResult` es que Cognito pide un paso más
        —`ChallengeName`— o que la respuesta no sirve. En los dos casos sale una
        excepción del dominio: el nombre del reto no cruza como dato, solo como
        texto de diagnóstico.
        """
        resultado = respuesta.get("AuthenticationResult")
        if not resultado:
            reto = respuesta.get("ChallengeName")
            if reto:
                raise AutenticacionIncompleta(reto=reto)
            raise CredencialesInvalidas()
        return Sesion(
            access_token=resultado.get("AccessToken"),
            id_token=resultado.get("IdToken"),
            refresh_token=resultado.get("RefreshToken"),
            expires_in=resultado.get("ExpiresIn", 3600),
        )

    # ── Autenticación ────────────────────────────────────────────────
    def autenticar(self, *, handle: str, password: str) -> Sesion:
        try:
            respuesta = self._cognito.initiate_auth(
                ClientId=settings.COGNITO_CLIENT_ID,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={
                    "USERNAME": handle,
                    "PASSWORD": password,
                    "SECRET_HASH": self._secret_hash(handle),
                },
            )
        except ClientError as exc:
            raise _traducir(exc) from exc
        return self._sesion_de(respuesta)

    def renovar(self, *, handle: str, refresh_token: str) -> Sesion:
        # El SECRET_HASH hace falta también aquí, y se calcula sobre el handle
        # aunque el flujo no lo mande como USERNAME.
        try:
            respuesta = self._cognito.initiate_auth(
                ClientId=settings.COGNITO_CLIENT_ID,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={
                    "REFRESH_TOKEN": refresh_token,
                    "SECRET_HASH": self._secret_hash(handle),
                },
            )
        except ClientError as exc:
            raise _traducir(exc) from exc
        return self._sesion_de(respuesta)

    def revocar_sesiones(self, *, access_token: str) -> None:
        try:
            self._cognito.global_sign_out(AccessToken=access_token)
        except ClientError as exc:
            raise _traducir(exc) from exc

    def verificar_token(self, token: str) -> dict:
        """Valida la firma del JWT contra las JWKS del pool.

        `verify_cognito_token` levanta `HTTPException` porque nació como
        dependencia de FastAPI y `deps.py` la sigue llamando directamente. Aquí
        se traduce al dominio para que la interfaz no obligue a nadie a conocer
        el framework; el día que `deps.py` pase por el proveedor —rebanada
        B3— la traducción al HTTP vuelve a hacerse allí, que es su sitio.
        """
        from app.core.security import verify_cognito_token

        try:
            return verify_cognito_token(token)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                raise CredencialesInvalidas(str(exc.detail)) from exc
            raise ErrorDelProveedor(
                str(exc.detail), codigo=str(exc.status_code)
            ) from exc

    # ── Ciclo de vida de la credencial ───────────────────────────────
    def sujeto_de(self, *, handle: str) -> Optional[str]:
        try:
            respuesta = self._cognito.admin_get_user(
                UserPoolId=settings.COGNITO_USER_POOL_ID,
                Username=handle,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "UserNotFoundException":
                # «No existe» es una respuesta, no un fallo: los dos sitios que
                # llaman a esto lo usan para decidir si crear la credencial.
                return None
            raise _traducir(exc) from exc
        return _sub_de(respuesta.get("UserAttributes", []))

    def crear_credencial(
        self,
        *,
        handle: str,
        email: str,
        full_name: Optional[str] = None,
        email_verificado: bool = False,
    ) -> Optional[str]:
        atributos = [
            {"Name": "email", "Value": email},
            {
                "Name": "email_verified",
                "Value": "true" if email_verificado else "false",
            },
        ]
        if full_name is not None:
            atributos.append({"Name": "name", "Value": full_name})

        try:
            respuesta = self._cognito.admin_create_user(
                UserPoolId=settings.COGNITO_USER_POOL_ID,
                Username=handle,
                UserAttributes=atributos,
                # Cognito no manda un solo correo en este sistema: los envía
                # SES, con la plantilla de la marca.
                MessageAction="SUPPRESS",
            )
        except ClientError as exc:
            raise _traducir(exc) from exc
        return _sub_de(respuesta.get("User", {}).get("Attributes", []))

    def fijar_password(self, *, handle: str, password: str) -> None:
        try:
            self._cognito.admin_set_user_password(
                UserPoolId=settings.COGNITO_USER_POOL_ID,
                Username=handle,
                Password=password,
                # Permanente: sin esto la credencial queda en
                # FORCE_CHANGE_PASSWORD y el siguiente login pide un reto.
                Permanent=True,
            )
        except ClientError as exc:
            raise _traducir(exc) from exc

    def marcar_correo_verificado(self, *, handle: str, email: str) -> None:
        # `email` viaja junto a `email_verified` porque Cognito lo exige: sin
        # él la llamada falla. Mandar el mismo correo que ya está puesto es
        # idempotente.
        try:
            self._cognito.admin_update_user_attributes(
                UserPoolId=settings.COGNITO_USER_POOL_ID,
                Username=handle,
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                ],
            )
        except ClientError as exc:
            raise _traducir(exc) from exc

import logging
import time
from threading import Lock

import requests
from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.core.config import settings

if getattr(settings, "COGNITO_ENDPOINT", None):
    JWKS_URL = (
        f"{settings.COGNITO_ENDPOINT}"
        f"/{settings.COGNITO_USER_POOL_ID}/.well-known/jwks.json"
    )
else:
    JWKS_URL = f"https://cognito-idp.{settings.COGNITO_REGION}.amazonaws.com/{settings.COGNITO_USER_POOL_ID}/.well-known/jwks.json"

logger = logging.getLogger(__name__)

_jwks_cache: dict = {}
_jwks_lock = Lock()
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 3600.0  # 1 hora


def _get_jwks() -> dict:
    """
    Obtiene las JWKS de Cognito con caché en memoria.
    TTL: 1 hora. Thread-safe con double-check locking.
    Si el endpoint de Cognito falla y hay caché expirada, la usa antes de lanzar error.
    """
    global _jwks_cache, _jwks_fetched_at

    now = time.monotonic()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL:
        return _jwks_cache

    with _jwks_lock:
        now = time.monotonic()
        if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL:
            return _jwks_cache

        try:
            resp = requests.get(JWKS_URL, timeout=5)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_fetched_at = time.monotonic()
        except Exception as e:
            if _jwks_cache:
                return _jwks_cache
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No se pudo verificar la autenticación",
            ) from e

    return _jwks_cache


def _token_invalido() -> HTTPException:
    """El 401 que ven todos los rechazos de credencial.

    Qué comprobación falló va al log y no a la respuesta: al cliente le sirve
    igual para reautenticarse, y a quien prueba tokens ajenos no le regala en
    qué se equivocó.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido",
    )


def _exigir_access_token_del_pool(payload: dict, *, log: str) -> None:
    """Lo que la firma **no** dice: de dónde viene el token, para qué se emitió
    y para quién.

    La firma sólo acredita que lo emitió este pool. No que sea un access token
    —un id token del mismo pool la pasa igual de bien— ni que se emitiera para
    este cliente. Medido contra `python-jose 3.5.0` el 26/09/2026:
    `audience=COGNITO_CLIENT_ID` no cubre lo último, porque los access tokens de
    Cognito llevan `client_id` y no `aud`, y el paquete acepta un token *sin*
    `aud` aunque se le pase `audience=` — el `raise` está comentado en el
    paquete. De ahí que estas comprobaciones estén escritas a mano.
    """
    if payload.get("iss") != _issuer_esperado():
        logger.warning("%s.issuer_ajeno", log)
        raise _token_invalido()

    if payload.get("token_use") != "access":
        logger.warning("%s.token_use_incorrecto: %s", log, payload.get("token_use"))
        raise _token_invalido()

    if payload.get("client_id") != settings.COGNITO_CLIENT_ID:
        logger.warning("%s.client_id_ajeno", log)
        raise _token_invalido()

    if not payload.get("sub"):
        logger.warning("%s.sin_sub", log)
        raise _token_invalido()


def verify_cognito_token(token: str) -> dict:
    """
    Valida un JWT de Cognito usando JWKS cacheadas.
    Firma original preservada para compatibilidad con deps.py.

    Exige un **access token de este pool**, con las mismas comprobaciones que
    `verificar_access_token_para_refresco` — la única diferencia entre las dos
    es `exp`, que allí se relaja a propósito y aquí no. Antes sólo se exigían de
    verdad la firma y `exp`, así que un id token servía donde se espera un
    access token: los dos llevan `sub`, y el `sub` es lo único que `deps.py`
    usa para encontrar al usuario.
    """
    try:
        jwks = _get_jwks()
        header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == header["kid"]), None)
        if not key:
            raise HTTPException(status_code=401, detail="Invalid token header")

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            # `verify_aud` fuera: para un access token es un no-op medido, y
            # quien comprueba de verdad para quién se emitió el token es la
            # exigencia de `client_id` de abajo.
            options={"verify_aud": False},
        )

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )

    _exigir_access_token_del_pool(payload, log="auth.token")
    return payload


def _issuer_esperado() -> str:
    """El `iss` que Cognito pone en los tokens de este pool.

    Se calcula al llamar y no al importar, a diferencia de `JWKS_URL`, porque es
    lo que permite apuntar a otro pool en una prueba sin recargar el módulo.
    """
    if getattr(settings, "COGNITO_ENDPOINT", None):
        return f"{settings.COGNITO_ENDPOINT}/{settings.COGNITO_USER_POOL_ID}"
    return (
        f"https://cognito-idp.{settings.COGNITO_REGION}.amazonaws.com"
        f"/{settings.COGNITO_USER_POOL_ID}"
    )


def verificar_access_token_para_refresco(token: str) -> dict:
    """Valida un access token de Cognito **admitiendo que esté vencido**.

    Es la pieza del contrato D2 de `/auth/refresh` (§24 del documento de
    arquitectura): el endpoint es público y necesita saber de quién es el
    refresh token, y la respuesta la trae el access token que el cliente ya
    tiene guardado — vencido, porque si no lo estuviera no estaría renovando.

    **Vive aparte de `verify_cognito_token` a propósito.** La alternativa era un
    parámetro `verificar_expiracion=False`, y entonces la relajación queda a un
    argumento de distancia de cualquier otro llamador. Aquí no se puede pasar
    por error: quien quiera saltarse `exp` tiene que llamar a una función que lo
    dice en el nombre.

    Y porque relaja `exp`, **endurece todo lo demás** con
    `_exigir_access_token_del_pool`: quitado `exp`, lo único que quedaría en pie
    sería la firma, y la firma sólo dice «lo emitió este pool», no «es el token
    que este endpoint espera». Esas comprobaciones nacieron aquí y hoy las
    comparte `verify_cognito_token`, que las necesitaba igual.

    El detalle que se devuelve al cliente es siempre el mismo — qué comprobación
    falló va al log y no a la respuesta.
    """
    try:
        jwks = _get_jwks()
        header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == header.get("kid")), None)
        if not key:
            logger.warning("auth.refresh.token.kid_desconocido")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido",
            )

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            options={"verify_exp": False, "verify_aud": False},
        )
    except JWTError as e:
        logger.warning("auth.refresh.token.firma_invalida: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        ) from e

    _exigir_access_token_del_pool(payload, log="auth.refresh.token")
    return payload

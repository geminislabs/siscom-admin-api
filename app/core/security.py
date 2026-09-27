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


def verify_cognito_token(token: str) -> dict:
    """
    Valida un JWT de Cognito usando JWKS cacheadas.
    Firma original preservada para compatibilidad con deps.py.
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
            audience=settings.COGNITO_CLIENT_ID,
        )
        return payload

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )


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

    Y porque relaja `exp`, **endurece todo lo demás**. Lo que sigue está medido
    contra `python-jose 3.5.0` el 26/09/2026, no deducido, y es la razón de que
    estas tres comprobaciones estén escritas a mano:

    - **`aud` no protege nada aquí.** Los access tokens de Cognito no llevan
      `aud` sino `client_id`, y python-jose acepta un token *sin* `aud` aunque se
      le pase `audience=` — el `raise` correspondiente está comentado en el
      paquete. `verify_cognito_token` pasa `audience=COGNITO_CLIENT_ID` y para un
      access token eso es un no-op.
    - **`token_use` no lo mira nadie.** Sin esa comprobación, un id token del
      mismo pool sirve igual que un access token.
    - Quitado `exp`, lo único que quedaría en pie sería la firma. Y la firma sólo
      dice «lo emitió este pool», no «es el token que este endpoint espera».

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

    esperado = _issuer_esperado()
    if payload.get("iss") != esperado:
        logger.warning("auth.refresh.token.issuer_ajeno")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido"
        )

    if payload.get("token_use") != "access":
        logger.warning(
            "auth.refresh.token.token_use_incorrecto: %s", payload.get("token_use")
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido"
        )

    if payload.get("client_id") != settings.COGNITO_CLIENT_ID:
        logger.warning("auth.refresh.token.client_id_ajeno")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido"
        )

    if not payload.get("sub"):
        logger.warning("auth.refresh.token.sin_sub")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido"
        )

    return payload

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

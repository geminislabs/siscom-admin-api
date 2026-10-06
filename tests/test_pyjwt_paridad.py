"""Lo que no puede cambiar al pasar de `python-jose` a PyJWT (06/10/2026).

El cambio de librería no debía tocar quién entra y quién no. Estos tests fijan
los puntos donde PyJWT, por defecto, se comporta distinto de `python-jose`:

- **`iat` en el futuro.** PyJWT lo rechaza con margen cero
  (`ImmatureSignatureError`); `python-jose` sólo exigía que fuera entero. Con
  el reloj del servidor un poco por detrás del de Cognito, un token recién
  emitido se habría rechazado. `_OPCIONES_COMUNES` desactiva esa comprobación.
- **Token malformado.** PyJWT lanza `DecodeError` desde
  `get_unverified_header`; tiene que seguir siendo un 401, no un 500.
- **JWK sin `alg`.** `jwt.PyJWK` necesita saber el algoritmo; Cognito publica
  `alg`, pero la llave no debe depender de ello: el algoritmo lo fija
  `algorithms=["RS256"]`.
"""

import time

import jwt
import pytest
from fastapi import HTTPException, status

from app.core import security
from app.core.security import (
    verificar_access_token_para_refresco,
    verify_cognito_token,
)
from tests import jwt_del_pool


@pytest.fixture
def clave_del_pool(monkeypatch):
    clave = jwt_del_pool.clave()
    monkeypatch.setattr(security, "_get_jwks", lambda: jwt_del_pool.jwks_de(clave))
    return clave


_VERIFICADORES = pytest.mark.parametrize(
    "verificar",
    [verify_cognito_token, verificar_access_token_para_refresco],
    ids=["verify_cognito_token", "para_refresco"],
)


@_VERIFICADORES
def test_iat_unos_segundos_en_el_futuro_se_acepta(clave_del_pool, verificar):
    """El desfase de reloj normal entre el servidor y Cognito."""
    token = jwt_del_pool.access_token(clave_del_pool, iat=int(time.time()) + 30)

    assert verificar(token)["sub"] == "test-cognito-sub-123"


@_VERIFICADORES
def test_token_malformado_es_401(clave_del_pool, verificar):
    with pytest.raises(HTTPException) as error:
        verificar("esto.no-es.un-jwt")

    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_jwk_sin_alg_sigue_verificando(clave_del_pool, monkeypatch):
    jwks = jwt_del_pool.jwks_de(clave_del_pool)
    del jwks["keys"][0]["alg"]
    monkeypatch.setattr(security, "_get_jwks", lambda: jwks)

    token = jwt_del_pool.access_token(clave_del_pool)

    assert verify_cognito_token(token)["sub"] == "test-cognito-sub-123"


def test_exp_vencido_sigue_rechazandose(clave_del_pool):
    """Desactivar `verify_iat` no relaja `exp`: sigue acotando el token."""
    ahora = int(time.time())
    token = jwt_del_pool.access_token(clave_del_pool, iat=ahora - 7200, exp=ahora - 60)

    with pytest.raises(HTTPException) as error:
        verify_cognito_token(token)

    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED


@_VERIFICADORES
def test_token_sin_kid_es_401(clave_del_pool, verificar):
    """Sin `kid` en la cabecera no hay llave que buscar: credencial inválida,
    no un 500. Pasaba en `verify_cognito_token` desde antes de PyJWT."""
    token = jwt.encode(
        {"sub": "x"}, jwt_del_pool.pem_privado(clave_del_pool), algorithm="RS256"
    )

    with pytest.raises(HTTPException) as error:
        verificar(token)

    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED

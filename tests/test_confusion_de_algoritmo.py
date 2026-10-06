"""CVE-2026-85394 (`python-jose` <= 3.5.0) no es explotable aquí: lo prueba
el ataque mismo, no un razonamiento.

El fallo: `python-jose` acepta como secreto HMAC una llave pública RSA en DER
(sin la armadura PEM que el arreglo de CVE-2024-33663 sí detecta). Quien tenga
la llave pública del servicio —y las JWKS de Cognito son públicas— puede
firmar un token HS256 que pase la verificación **si `jwt.decode` no restringe
los algoritmos**.

Aquí hay dos barreras, medidas el 06/10/2026:

1. Los dos únicos `jwt.decode` del servicio (`app/core/security.py`) pasan
   `algorithms=["RS256"]`, así que un token HS256 se rechaza antes de mirar
   la llave.
2. La llave llega de las JWKS como JWK (`kty: RSA`), no como bytes. Aun
   permitiendo HS256, `python-jose` no la acepta como secreto HMAC
   (`JWKError: Incorrect key type`) — el ataque necesita la llave en bytes.

Estos tests fabrican el token del ataque —HS256, firmado con la llave pública
en DER y en PEM, con los claims de un access token válido— y exigen un 401 de
las dos funciones. Quitar la primera barrera cambia ese resultado —medido: con
HS256 permitido escapa un `JWKError` en vez del 401—, así que esto vigila el
uso del que depende la excepción de `scripts/pip-audit-scan.sh`. Quitar sólo
la segunda no lo cambiaría, porque la primera sigue rechazando: la segunda es
defensa en profundidad, no lo que el test fija. Ver
`docs/security/threat-model.md`, Riesgos aceptados.
"""

import base64
import hashlib
import hmac
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException, status

from app.core import security
from app.core.config import settings
from app.core.security import (
    _issuer_esperado,
    verificar_access_token_para_refresco,
    verify_cognito_token,
)
from tests import jwt_del_pool


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode()


def _hs256_firmado_con(secreto: bytes) -> str:
    """El token del ataque, construido a mano para no depender de lo que
    `python-jose` deje o no deje firmar."""
    ahora = int(time.time())
    cabecera = {"alg": "HS256", "typ": "JWT", "kid": jwt_del_pool.KID}
    claims = {
        "sub": "test-cognito-sub-123",
        "token_use": "access",
        "client_id": settings.COGNITO_CLIENT_ID,
        "iss": _issuer_esperado(),
        "iat": ahora - 60,
        "exp": ahora + 3600,
    }
    firmado = (
        _b64(json.dumps(cabecera).encode()) + "." + _b64(json.dumps(claims).encode())
    )
    firma = hmac.new(secreto, firmado.encode(), hashlib.sha256).digest()
    return firmado + "." + _b64(firma)


@pytest.fixture
def clave_del_pool(monkeypatch):
    clave = jwt_del_pool.clave()
    monkeypatch.setattr(security, "_get_jwks", lambda: jwt_del_pool.jwks_de(clave))
    return clave


def _publica(clave, codificacion) -> bytes:
    return clave.public_key().public_bytes(
        codificacion, serialization.PublicFormat.SubjectPublicKeyInfo
    )


@pytest.mark.parametrize(
    "codificacion",
    [serialization.Encoding.DER, serialization.Encoding.PEM],
    ids=["der", "pem"],
)
@pytest.mark.parametrize(
    "verificar",
    [verify_cognito_token, verificar_access_token_para_refresco],
    ids=["verify_cognito_token", "para_refresco"],
)
def test_hs256_firmado_con_la_llave_publica_se_rechaza(
    clave_del_pool, codificacion, verificar
):
    token = _hs256_firmado_con(_publica(clave_del_pool, codificacion))

    with pytest.raises(HTTPException) as error:
        verificar(token)

    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED


def test_el_mismo_contenido_firmado_en_rs256_si_pasa(clave_del_pool):
    """Control: el rechazo de arriba es por el algoritmo, no porque los
    claims del token fabricado estén mal."""
    assert verify_cognito_token(jwt_del_pool.access_token(clave_del_pool))["sub"] == (
        "test-cognito-sub-123"
    )

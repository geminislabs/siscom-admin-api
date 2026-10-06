"""Tokens firmados de verdad, con la forma que emite Cognito.

Se genera una clave RSA y se sustituyen las JWKS del pool por la suya, en vez de
sobreescribir la dependencia de autenticación. Es la diferencia entre probar el
contrato y probar el doble: con la dependencia sustituida no se ejercita
*ninguna* de las comprobaciones reales —firma, `iss`, `token_use`,
`client_id`—, que son justo las que estos tests existen para fijar.

Vive en su propio módulo para que «un token como los de Cognito» tenga **una
sola definición**. Dos copias divergen, y la que divergiera dejaría de
representar a Cognito sin que ningún test se quejara.
"""

import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.core.config import settings
from app.core.security import _issuer_esperado

KID = "kid-de-prueba"


def clave():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def pem_privado(clave):
    return clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def jwks_de(clave):
    """Las JWKS con la forma que publica Cognito: `kty`, `n`, `e` como texto,
    más `kid`, `alg` y `use`."""
    entrada = RSAAlgorithm.to_jwk(clave.public_key(), as_dict=True)
    entrada.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [entrada]}


def _ahora() -> int:
    """El epoch de verdad, y **no** `utcnow().timestamp()`.

    `app.utils.datetime.utcnow()` devuelve UTC *naive* a propósito, y
    `.timestamp()` interpreta un naive como hora **local**: en UTC-6 adelanta
    seis horas. Un `exp` construido así no vence donde se escribió el test, y sí
    vence en la CI, que corre en UTC — la clase de test que pasa por el sitio
    equivocado en una máquina y por el bueno en la otra. Un claim de JWT es
    epoch absoluto: no hay zona que aplicarle.
    """
    return int(time.time())


def firmar(clave, claims: dict) -> str:
    return jwt.encode(
        claims, pem_privado(clave), algorithm="RS256", headers={"kid": KID}
    )


def access_token(clave, **sobrescribe) -> str:
    """Un access token vigente del pool. `sobrescribe` cambia o quita claims.

    El `sub` es el de `test_user_data`: así el token identifica a esa fila sin
    que cada test tenga que decirlo.
    """
    ahora = _ahora()
    claims = {
        "sub": "test-cognito-sub-123",
        "token_use": "access",
        "client_id": settings.COGNITO_CLIENT_ID,
        "iss": _issuer_esperado(),
        "iat": ahora - 60,
        "exp": ahora + 3600,
    }
    claims.update(sobrescribe)
    return firmar(clave, {k: v for k, v in claims.items() if v is not None})


def id_token(clave, **sobrescribe) -> str:
    """Un id token del **mismo** pool, con su forma real: lleva `aud` en vez de
    `client_id`, y `token_use` vale `id`.

    Está tan bien firmado como el access token. Lo único que lo distingue son
    los claims, y de ahí que haya que mirarlos.
    """
    ahora = _ahora()
    claims = {
        "sub": "test-cognito-sub-123",
        "token_use": "id",
        "aud": settings.COGNITO_CLIENT_ID,
        "email": "test@example.com",
        "iss": _issuer_esperado(),
        "iat": ahora - 60,
        "exp": ahora + 3600,
    }
    claims.update(sobrescribe)
    return firmar(clave, {k: v for k, v in claims.items() if v is not None})

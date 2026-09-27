"""Contrato D2 de `POST /auth/refresh` — §24 del documento de arquitectura.

La identidad sale de la cabecera `Authorization`, **admitiendo que el access
token esté vencido**: si no lo estuviera, el cliente no estaría renovando.

POR QUÉ ESTOS TESTS FIRMAN DE VERDAD
====================================
Se genera una clave RSA y se sustituye el JWKS de Cognito por el suyo, en vez de
sobreescribir la dependencia de autenticación. Es la diferencia entre probar el
contrato y probar el doble: con la dependencia sustituida, *ninguna* de estas
comprobaciones —firma, `iss`, `token_use`, `client_id`— se ejercitaría, y el
endpoint que relaja `exp` es justo el que no puede permitirse eso.

Cada rechazo comprueba además que **no se llamó al proveedor**. Un 401 después
de haber hablado con Cognito sería otro fallo con la misma pinta.
"""

from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import status
from jose import jwk, jwt

from app.api.deps import get_identity_provider
from app.core import security
from app.core.config import settings
from app.core.security import _issuer_esperado
from app.main import app as fastapi_app
from app.services.identity import IdentityProvider, Sesion
from app.utils.datetime import utcnow

KID = "kid-de-prueba"


def _clave():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem_privado(clave):
    return clave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _jwks_de(clave):
    pem = (
        clave.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    entrada = jwk.construct(pem, "RS256").to_dict()
    entrada["kid"] = KID
    # `to_dict()` devuelve `n` y `e` en bytes; el decodificador los quiere como
    # texto, igual que vienen del endpoint real de Cognito.
    return {
        "keys": [
            {k: (v.decode() if isinstance(v, bytes) else v) for k, v in entrada.items()}
        ]
    }


@pytest.fixture
def clave_del_pool(monkeypatch):
    """Sustituye las JWKS de Cognito por una clave local."""
    clave = _clave()
    monkeypatch.setattr(security, "_get_jwks", lambda: _jwks_de(clave))
    return clave


@pytest.fixture
def idp_falso():
    doble = MagicMock(spec=IdentityProvider)
    doble.renovar.return_value = Sesion(
        access_token="access-nuevo",
        id_token="id-nuevo",
        refresh_token=None,
        expires_in=3600,
    )
    fastapi_app.dependency_overrides[get_identity_provider] = lambda: doble
    yield doble
    fastapi_app.dependency_overrides.pop(get_identity_provider, None)


def _access_token(clave, **sobrescribe):
    """Un access token con la forma que emite Cognito. Vencido a propósito."""
    claims = {
        "sub": "test-cognito-sub-123",
        "token_use": "access",
        "client_id": settings.COGNITO_CLIENT_ID,
        "iss": _issuer_esperado(),
        "exp": int(utcnow().timestamp()) - 3600,
        "iat": int(utcnow().timestamp()) - 7200,
    }
    claims.update(sobrescribe)
    return jwt.encode(
        claims, _pem_privado(clave), algorithm="RS256", headers={"kid": KID}
    )


def _renovar(client, token=None, cuerpo=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        "/api/v1/auth/refresh",
        json=cuerpo or {"refresh_token": "refresh-guardado"},
        headers=headers,
    )


# ── El camino nuevo ───────────────────────────────────────────────────────


def test_cabecera_vencida_renueva_con_el_external_id_de_la_fila(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Es el punto entero de D2: el token vencido sigue identificando."""
    assert test_user_data.external_id, "la 028 rellena el handle en el alta"

    respuesta = _renovar(client, _access_token(clave_del_pool))

    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.json()["access_token"] == "access-nuevo"
    idp_falso.renovar.assert_called_once_with(
        handle=test_user_data.external_id,
        refresh_token="refresh-guardado",
    )


def test_la_cabecera_gana_al_email_del_cuerpo(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Durante la transición los dos campos pueden venir; manda el firmado."""
    respuesta = _renovar(
        client,
        _access_token(clave_del_pool),
        cuerpo={
            "email": "otra.persona@example.com",
            "refresh_token": "refresh-guardado",
        },
    )

    assert respuesta.status_code == status.HTTP_200_OK
    _, kwargs = idp_falso.renovar.call_args
    assert kwargs["handle"] == test_user_data.external_id
    assert kwargs["handle"] != "otra.persona@example.com"


# ── Lo que se valida, una comprobación por test ───────────────────────────


def test_firma_de_otra_clave_es_401(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Mismo `kid`, otra clave: la firma es lo único que lo distingue."""
    respuesta = _renovar(client, _access_token(_clave()))

    assert respuesta.status_code == status.HTTP_401_UNAUTHORIZED
    idp_falso.renovar.assert_not_called()


def test_un_id_token_no_sirve(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Está firmado por el mismo pool y aun así no es este token.

    Sin la comprobación de `token_use` pasaría: python-jose no la mira, y la
    verificación normal tampoco.
    """
    respuesta = _renovar(client, _access_token(clave_del_pool, token_use="id"))

    assert respuesta.status_code == status.HTTP_401_UNAUTHORIZED
    idp_falso.renovar.assert_not_called()


def test_client_id_de_otra_aplicacion_es_401(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """`aud` no cubre esto: los access tokens de Cognito llevan `client_id`."""
    respuesta = _renovar(client, _access_token(clave_del_pool, client_id="otra-app"))

    assert respuesta.status_code == status.HTTP_401_UNAUTHORIZED
    idp_falso.renovar.assert_not_called()


def test_issuer_de_otro_pool_es_401(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    respuesta = _renovar(
        client,
        _access_token(
            clave_del_pool, iss="https://cognito-idp.us-east-1.amazonaws.com/otro"
        ),
    )

    assert respuesta.status_code == status.HTTP_401_UNAUTHORIZED
    idp_falso.renovar.assert_not_called()


def test_sub_que_no_tiene_fila_es_401_y_no_404(
    client, db_session, clave_del_pool, idp_falso
):
    """404 diría «ese usuario no existe» a quien no está autenticado."""
    respuesta = _renovar(client, _access_token(clave_del_pool, sub="sub-que-no-existe"))

    assert respuesta.status_code == status.HTTP_401_UNAUTHORIZED
    idp_falso.renovar.assert_not_called()


def test_cabecera_mal_formada_cae_al_camino_del_email(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Un esquema que no es Bearer se ignora; no se toma el valor como token."""
    respuesta = client.post(
        "/api/v1/auth/refresh",
        json={"email": "usuario@example.com", "refresh_token": "refresh-guardado"},
        headers={"Authorization": "Basic dXN1YXJpbzpjbGF2ZQ=="},
    )

    assert respuesta.status_code == status.HTTP_200_OK
    _, kwargs = idp_falso.renovar.call_args
    assert kwargs["handle"] == "usuario@example.com"


# ── El camino heredado, que no se rompe ───────────────────────────────────


def test_solo_email_sigue_funcionando(client, db_session, idp_falso):
    """`nexus-web` manda esto hoy, y quita la cabecera a propósito."""
    respuesta = _renovar(
        client,
        cuerpo={"email": "usuario@example.com", "refresh_token": "refresh-guardado"},
    )

    assert respuesta.status_code == status.HTTP_200_OK
    idp_falso.renovar.assert_called_once_with(
        handle="usuario@example.com",
        refresh_token="refresh-guardado",
    )


def test_sin_cabecera_y_sin_email_sigue_siendo_422(client, db_session, idp_falso):
    """iOS y Android mandan sólo el refresh token y hoy reciben 422 (§13).

    Después de este cambio reciben exactamente lo mismo: una app vieja no queda
    peor de lo que estaba.
    """
    respuesta = _renovar(client)

    assert respuesta.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    idp_falso.renovar.assert_not_called()

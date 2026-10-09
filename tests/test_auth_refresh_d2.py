"""Contrato D2 de `POST /auth/refresh` — §24 del documento de arquitectura.

La identidad sale de la cabecera `Authorization`, **admitiendo que el access
token esté vencido**: si no lo estuviera, el cliente no estaría renovando.

Desde el 28/09/2026 es el **único** camino: el campo `email` del cuerpo, por el
que se firmaba cuando handle == correo, está borrado.

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

import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_identity_provider
from app.core import security
from app.main import app as fastapi_app
from app.models.account import Account
from app.services.identity import (
    ErrorDelProveedor,
    IdentityProvider,
    ProveedorSaturado,
    Sesion,
)
from tests import jwt_del_pool


@pytest.fixture
def clave_del_pool(monkeypatch):
    """Sustituye las JWKS de Cognito por una clave local."""
    clave = jwt_del_pool.clave()
    monkeypatch.setattr(security, "_get_jwks", lambda: jwt_del_pool.jwks_de(clave))
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
    """Un access token con la forma que emite Cognito. **Vencido a propósito**:
    es la condición que este endpoint admite y ningún otro.

    El `exp` se calcula desde `time.time()` y no desde `utcnow().timestamp()`,
    que adelanta seis horas en UTC-6 y dejaba el token *vigente* al correr los
    tests en local — vencía sólo en la CI. Ver `tests/jwt_del_pool.py`.
    """
    ahora = int(time.time())
    sobrescribe.setdefault("exp", ahora - 3600)
    sobrescribe.setdefault("iat", ahora - 7200)
    return jwt_del_pool.access_token(clave, **sobrescribe)


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


def test_un_email_en_el_cuerpo_se_ignora(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Un cliente viejo que todavía mande el correo no se rompe: sobra.

    El campo se borró del esquema el 28/09/2026 y Pydantic descarta lo que
    sobra, así que un cuerpo heredado con cabecera renueva igual — y **nunca**
    con el correo como handle, que es lo que este test vigila.
    """
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
    respuesta = _renovar(client, _access_token(jwt_del_pool.clave()))

    assert respuesta.status_code == status.HTTP_401_UNAUTHORIZED
    idp_falso.renovar.assert_not_called()


def test_un_id_token_no_sirve(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Está firmado por el mismo pool y aun así no es este token.

    Sin la comprobación de `token_use` pasaría: la librería JWT no la mira, y
    la verificación normal tampoco.
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


def test_cabecera_mal_formada_es_422_y_no_se_toma_por_token(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Un esquema que no es Bearer se ignora; no se toma el valor como token.

    Antes esto caía al camino del correo y devolvía 200. Ahora no hay dónde
    caer: sin cabecera válida es 422, y el valor de un `Basic` **no** llega a
    tratarse como un token.
    """
    respuesta = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "refresh-guardado"},
        headers={"Authorization": "Basic dXN1YXJpbzpjbGF2ZQ=="},
    )

    assert respuesta.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    idp_falso.renovar.assert_not_called()


# ── El camino heredado, ya borrado ────────────────────────────────────────


def test_solo_email_ya_no_renueva(client, db_session, idp_falso):
    """El correo dejó de ser identidad el 28/09/2026.

    Es el test que invierte a `test_solo_email_sigue_funcionando`, y es el que
    prueba que el camino se fue de verdad: antes esto devolvía 200 firmando el
    `SECRET_HASH` con el correo. Ahora es 422 y **no se llama al proveedor** —
    que importa, porque firmar con un handle que ya no existe daría un 401
    indistinguible de un refresh token inválido.
    """
    respuesta = _renovar(
        client,
        cuerpo={"email": "usuario@example.com", "refresh_token": "refresh-guardado"},
    )

    assert respuesta.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    idp_falso.renovar.assert_not_called()


def test_sin_cabecera_sigue_siendo_422(client, db_session, idp_falso):
    """El código no cambia para quien no manda nada.

    Es lo que recibían iOS y Android antes del pase del 28/09 (§13), y lo que
    siguen recibiendo las versiones que están en la calle: una app vieja no
    queda peor de lo que estaba.
    """
    respuesta = _renovar(client)

    assert respuesta.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    idp_falso.renovar.assert_not_called()


# ── El token rotado ───────────────────────────────────────────────────────
#
# Cognito sabe rotar refresh tokens y en este pool está apagado
# (`RefreshTokenRotation: null`). El día que se encienda devolverá uno nuevo en
# cada renovación y el anterior dejará de valer pasado el periodo de gracia. El
# endpoint tiene que reenviarlo **antes** de que eso pase: si no, todo el mundo
# acaba en la pantalla de login. Por eso estos dos tests son el paso 1 del orden
# de §24 y no van después de activar la rotación.
#
# Vivían en `test_auth.py` y renovaban por el camino del correo. Al borrarse ese
# camino se mudan aquí, que es donde están las fixtures que firman de verdad.


def test_refresh_reenvia_el_token_rotado(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Si el proveedor devuelve un refresh token nuevo, el cliente lo recibe."""
    idp_falso.renovar.return_value = Sesion(
        access_token="access-nuevo",
        id_token="id-nuevo",
        refresh_token="refresh-rotado",
        expires_in=3600,
    )

    respuesta = _renovar(
        client,
        _access_token(clave_del_pool),
        cuerpo={"refresh_token": "refresh-viejo"},
    )

    assert respuesta.status_code == status.HTTP_200_OK
    cuerpo = respuesta.json()
    assert cuerpo["refresh_token"] == "refresh-rotado"
    assert cuerpo["access_token"] == "access-nuevo"
    idp_falso.renovar.assert_called_once_with(
        handle=test_user_data.external_id, refresh_token="refresh-viejo"
    )


def test_refresh_sin_rotacion_devuelve_el_campo_nulo(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Es el comportamiento de hoy, y tiene que seguir siendo válido.

    Sin rotación Cognito no manda `RefreshToken`, así que el campo sale `null`
    en vez de ausente o vacío: el cliente distingue «no hay uno nuevo» de «toma
    éste» sin adivinar. Los tres clientes ya lo tratan así — la web desde
    `setSession()`, y los móviles desde el pase del 28/09.
    """
    idp_falso.renovar.return_value = Sesion(
        access_token="access-nuevo",
        id_token="id-nuevo",
        refresh_token=None,
        expires_in=3600,
    )

    respuesta = _renovar(
        client,
        _access_token(clave_del_pool),
        cuerpo={"refresh_token": "refresh-viejo"},
    )

    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.json()["refresh_token"] is None


# ── Proveedor por marca (post-B3) ───────────────────────────────────────────


def test_renovacion_usa_el_proveedor_de_la_marca_de_la_fila(
    client, db_session, test_user_data, clave_del_pool
):
    """
    `idp` se sobreescribe con el proveedor de la marca de la fila resuelta por
    el `sub` —no el proveedor por defecto inyectado en la firma— en cuanto esa
    fila tiene `brand_account_id`. Hoy ninguna lo tiene en producción
    (`get_identity_provider` sigue siendo lo que ve el 100% del tráfico), pero
    el día que exista una marca con su propio Cognito, renovar su sesión no
    puede seguir hablándole al pool por defecto.
    """
    marca = Account(id=uuid4(), name="Mero Mero", status="ACTIVE")
    db_session.add(marca)
    db_session.flush()
    test_user_data.brand_account_id = marca.id
    db_session.commit()

    proveedor_de_marca = MagicMock(spec=IdentityProvider)
    proveedor_de_marca.renovar.return_value = Sesion(
        access_token="access-marca",
        id_token="id-marca",
        refresh_token=None,
        expires_in=3600,
    )

    with patch(
        "app.api.v1.endpoints.auth.proveedor_para_cuenta",
        return_value=proveedor_de_marca,
    ) as resolver:
        respuesta = _renovar(client, _access_token(clave_del_pool))

    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.json()["access_token"] == "access-marca"
    resolver.assert_called_once()
    assert resolver.call_args.args[0].id == marca.id
    proveedor_de_marca.renovar.assert_called_once_with(
        handle=test_user_data.external_id, refresh_token="refresh-guardado"
    )


def test_cognito_limitado_es_429_y_no_500(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    """Con la rotación activa, varias pestañas renovando a la vez hacían que
    Cognito respondiera `TooManyRequestsException` (producción, 09/10/2026), y
    el endpoint lo devolvía como 500. El refresh token sigue valiendo: es un
    «vuelve luego», y el cliente necesita poder distinguirlo de un rechazo.
    """
    idp_falso.renovar.side_effect = ProveedorSaturado(
        "Rate exceeded", codigo="TooManyRequestsException"
    )

    respuesta = _renovar(client, _access_token(clave_del_pool))

    assert respuesta.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert respuesta.headers["Retry-After"] == "30"
    assert "Rate exceeded" not in respuesta.json()["detail"]


def test_otro_fallo_del_proveedor_sigue_siendo_500(
    client, db_session, test_user_data, clave_del_pool, idp_falso
):
    idp_falso.renovar.side_effect = ErrorDelProveedor(
        "algo raro", codigo="InternalErrorException"
    )

    respuesta = _renovar(client, _access_token(clave_del_pool))

    assert respuesta.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

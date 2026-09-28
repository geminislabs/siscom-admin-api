"""Qué se exige de verdad en el camino normal de autenticación.

`verify_cognito_token` es la puerta de toda la API autenticada: `deps.py` la
llama y se queda con el `sub` para encontrar la fila del usuario. Hasta el
28/09/2026 sólo exigía **la firma y `exp`** — pasaba `audience=` creyendo cubrir
para quién se emitió el token, y eso es un no-op medido: los access tokens de
Cognito llevan `client_id` y no `aud`, y `python-jose` acepta un token *sin*
`aud` aunque se le pase `audience=`.

La consecuencia era que **un id token del mismo pool servía donde se espera un
access token**. Los dos llevan `sub`, y el `sub` es lo único que se mira después.

Estos tests firman de verdad contra unas JWKS sustituidas (ver
`tests/jwt_del_pool.py`): con la dependencia de auth sobreescrita, ninguna de
estas comprobaciones se ejercitaría.
"""

import time

import pytest
from fastapi import HTTPException, status

from app.core import security
from app.core.security import verify_cognito_token
from tests import jwt_del_pool


@pytest.fixture
def clave_del_pool(monkeypatch):
    """Sustituye las JWKS de Cognito por una clave local."""
    clave = jwt_del_pool.clave()
    monkeypatch.setattr(security, "_get_jwks", lambda: jwt_del_pool.jwks_de(clave))
    return clave


def _rechazo(token) -> HTTPException:
    with pytest.raises(HTTPException) as capturado:
        verify_cognito_token(token)
    return capturado.value


# ── Lo que se acepta ──────────────────────────────────────────────────────


def test_un_access_token_del_pool_se_acepta(clave_del_pool):
    payload = verify_cognito_token(jwt_del_pool.access_token(clave_del_pool))

    assert payload["sub"] == "test-cognito-sub-123"
    assert payload["token_use"] == "access"


# ── Lo que se rechaza, una comprobación por test ──────────────────────────


def test_un_id_token_del_mismo_pool_ya_no_sirve(clave_del_pool):
    """El agujero que cierra este cambio.

    El id token está tan bien firmado como el access token y lleva el mismo
    `sub`, así que antes autenticaba igual. Un id token viaja a más sitios —es
    el que lleva los datos del perfil— y no es el que esta API espera.
    """
    rechazo = _rechazo(jwt_del_pool.id_token(clave_del_pool))

    assert rechazo.status_code == status.HTTP_401_UNAUTHORIZED
    assert rechazo.detail == "Token inválido"


def test_un_token_de_otra_app_del_pool_no_sirve(clave_del_pool):
    """Mismo pool, otro `client_id`: es lo que `audience=` prometía cubrir."""
    token = jwt_del_pool.access_token(clave_del_pool, client_id="otra-app-del-pool")

    assert _rechazo(token).status_code == status.HTTP_401_UNAUTHORIZED


def test_un_token_de_otro_pool_no_sirve(clave_del_pool):
    """La firma se comprueba contra las JWKS de este pool, pero el `iss` dice
    de qué pool afirma venir el token. Si no coinciden, no se discute."""
    token = jwt_del_pool.access_token(
        clave_del_pool, iss="https://cognito-idp.us-east-1.amazonaws.com/otro_pool"
    )

    assert _rechazo(token).status_code == status.HTTP_401_UNAUTHORIZED


def test_un_access_token_sin_client_id_no_sirve(clave_del_pool):
    """Quitar el claim no es lo mismo que traerlo mal, y `python-jose` no
    distingue: por eso la comprobación es una igualdad y no un `if presente`."""
    token = jwt_del_pool.access_token(clave_del_pool, client_id=None)

    assert _rechazo(token).status_code == status.HTTP_401_UNAUTHORIZED


def test_aqui_exp_sigue_exigiendose(clave_del_pool):
    """La diferencia con `verificar_access_token_para_refresco`, que lo relaja a
    propósito. El mismo token vencido vale allí y no vale aquí."""
    vencido = jwt_del_pool.access_token(clave_del_pool, exp=int(time.time()) - 3600)

    assert _rechazo(vencido).status_code == status.HTTP_401_UNAUTHORIZED


# ── El camino completo, por HTTP ──────────────────────────────────────────


def test_por_http_el_id_token_no_abre_lo_que_el_access_token_abre(
    client, db_session, test_user_data, clave_del_pool
):
    """La prueba de que esto pasa por `deps.py` y no sólo por la función.

    Las dos peticiones son idénticas —mismo endpoint, mismo pool, misma clave,
    mismo `sub`— y sólo cambia qué token se manda. Antes las dos respondían 200.
    """
    con_access = client.get(
        "/api/v1/alerts",
        headers={
            "Authorization": f"Bearer {jwt_del_pool.access_token(clave_del_pool)}"
        },
    )
    con_id = client.get(
        "/api/v1/alerts",
        headers={"Authorization": f"Bearer {jwt_del_pool.id_token(clave_del_pool)}"},
    )

    assert con_access.status_code == status.HTTP_200_OK
    assert con_id.status_code == status.HTTP_401_UNAUTHORIZED

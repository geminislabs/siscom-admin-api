"""
Tests de autenticación.
Verifica que los endpoints protegidos rechacen requests sin token válido.

CÓMO SE SUSTITUYE EL PROVEEDOR DE IDENTIDAD
===========================================
Estos tests no parchean módulos: sustituyen la dependencia
`get_identity_provider` por un doble. Antes parcheaban
`app.api.v1.endpoints.auth.cognito`, el cliente de boto3 que vivía en ese
módulo; desde la rebanada B1 el endpoint solo conoce la interfaz.

Lo que Cognito exige en cada llamada —el `MessageAction`, el atributo `email`
junto a `email_verified`, el `Permanent` de la contraseña— se comprueba en
`tests/test_identidad_codigo.py`, contra el adaptador. Aquí se comprueba lo que
es de este endpoint: a quién llama y con qué handle.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_identity_provider
from app.main import app as fastapi_app
from app.models.token_confirmacion import TokenConfirmacion, TokenType
from app.services.identity import IdentityProvider, Sesion
from app.utils.datetime import utcnow


@pytest.fixture
def idp_falso():
    """Un `IdentityProvider` de mentira, puesto por `dependency_overrides`.

    `spec=IdentityProvider` es lo que hace que el doble no acepte métodos que
    la interfaz no tiene: un test que se quede escrito contra una firma vieja
    falla en vez de pasar contra un mock complaciente.
    """
    doble = MagicMock(spec=IdentityProvider)
    doble.autenticar.return_value = Sesion(
        access_token="access",
        id_token="id",
        refresh_token="refresh",
        expires_in=3600,
    )
    fastapi_app.dependency_overrides[get_identity_provider] = lambda: doble
    yield doble
    fastapi_app.dependency_overrides.pop(get_identity_provider, None)


def test_endpoint_without_token_returns_401(client):
    """GET /organizations requiere autenticación."""
    response = client.get("/api/v1/organizations")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_missing_credentials_sets_www_authenticate_header(client):
    """RFC 9110 exige `WWW-Authenticate` en las respuestas 401."""
    response = client.get("/api/v1/organizations")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


def test_non_bearer_scheme_returns_401_with_www_authenticate(client):
    """Un esquema distinto de Bearer es 'no sé quién eres', no 'no puedes'."""
    headers = {"Authorization": "Basic dXNlcjpwYXNz"}
    response = client.get("/api/v1/organizations", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.headers["www-authenticate"] == "Bearer"


def test_endpoint_with_invalid_token_returns_401(client):
    """Token inválido en endpoint protegido."""
    headers = {"Authorization": "Bearer invalid_token_here"}
    response = client.get("/api/v1/organizations", headers=headers)
    assert response.status_code in [
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ]


def test_devices_my_devices_endpoint_without_auth(client):
    """GET /devices/my-devices requiere autenticación."""
    response = client.get("/api/v1/devices/my-devices")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_verify_email_existing_cognito_user_sends_email_attribute(
    client, db_session, test_user_data, idp_falso
):
    """
    Cubre la rama de usuario master cuya credencial ya existe (Flujo A).

    Que la llamada a Cognito lleve `email` junto a `email_verified` —sin él
    falla— lo comprueba `test_marcar_verificado_manda_el_correo_junto_al_email_verified`.
    """
    token_value = "verify-existing-cognito-user"
    token_record = TokenConfirmacion(
        id=uuid4(),
        token=token_value,
        expires_at=utcnow() + timedelta(hours=1),
        used=False,
        type=TokenType.EMAIL_VERIFICATION,
        user_id=test_user_data.id,
        email=test_user_data.email,
        password_temp="TempPass123!",
    )
    db_session.add(token_record)
    db_session.commit()

    existing_sub = "existing-cognito-sub-456"
    idp_falso.sujeto_de.return_value = existing_sub

    response = client.post(f"/api/v1/auth/verify-email?token={token_value}")

    assert response.status_code == status.HTTP_200_OK
    # La credencial ya estaba: no se recrea, se le fija la contraseña y se le
    # marca el correo como verificado.
    idp_falso.crear_credencial.assert_not_called()
    idp_falso.fijar_password.assert_called_once()
    idp_falso.marcar_correo_verificado.assert_called_once_with(
        handle=test_user_data.external_id,
        email=test_user_data.email,
    )

    db_session.refresh(test_user_data)
    db_session.refresh(token_record)
    assert test_user_data.email_verified is True
    assert test_user_data.cognito_sub == existing_sub
    assert token_record.used is True
    assert token_record.password_temp is None


# ---------------------------------------------------------------------------
# Data token adjunto al login (Fase 1)
# ---------------------------------------------------------------------------


def _make_verified_user(db_session, test_organization_data):
    from app.models.user import User

    user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        email="login-datatoken@example.com",
        full_name="Login Test",
        email_verified=True,
        is_master=True,
        cognito_sub=str(uuid4()),
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_login_without_data_plane_still_succeeds(
    client, db_session, test_organization_data, idp_falso
):
    """
    El plano de datos no puede impedir iniciar sesión. Sin Valkey el usuario entra
    igual y verá la aplicación sin mapa, en vez de no poder entrar; el cliente lo
    reintenta luego contra `POST /auth/data-token`, que ahí sí devuelve 503.
    """
    from app.api.deps import get_scope_store
    from app.services.scope_store import ScopeStore

    user = _make_verified_user(db_session, test_organization_data)
    fastapi_app.dependency_overrides[get_scope_store] = lambda: ScopeStore(None)

    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "irrelevante"},
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_scope_store, None)

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["data_token"] is None
    # Las credenciales de sesión siguen llegando
    assert body["access_token"] == "access"


# ---------------------------------------------------------------------------
# El handle, que no es el correo (Fase 3, rebanada B1)
# ---------------------------------------------------------------------------


def test_login_autentica_con_el_handle_de_la_fila_no_con_el_correo(
    client, db_session, test_organization_data, idp_falso
):
    """
    Es lo que hace posible la rebanada B2: el día que un alta nueva nazca con
    handle UUID, este endpoint ya autentica con él. Hoy los dos valores
    coinciden en toda fila existente —la 028 rellenó `external_id` desde el
    correo— así que la diferencia solo se ve forzándola.
    """
    from app.models.user import User

    handle = str(uuid4())
    user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        email="handle-distinto@example.com",
        full_name="Handle Distinto",
        email_verified=True,
        external_id=handle,
        cognito_sub=str(uuid4()),
    )
    db_session.add(user)
    db_session.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "irrelevante"},
    )

    assert response.status_code == status.HTTP_200_OK
    idp_falso.autenticar.assert_called_once_with(handle=handle, password="irrelevante")


def test_una_contrasena_mala_sigue_siendo_un_401_con_el_mensaje_del_proveedor(
    client, db_session, test_organization_data, idp_falso
):
    """La traducción al HTTP no cambió con el refactor: mismo código, mismo
    detalle. Lo que cambió es de dónde sale —una clase del dominio en vez de
    un `ClientError`— y eso no puede notarse desde fuera.
    """
    from app.services.identity import CredencialesInvalidas

    user = _make_verified_user(db_session, test_organization_data)
    idp_falso.autenticar.side_effect = CredencialesInvalidas(
        "Incorrect username or password.", codigo="NotAuthorizedException"
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "la-que-no-es"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == (
        "Credenciales inválidas. Incorrect username or password."
    )


# ---------------------------------------------------------------------------
# Revocación al cambiar y restablecer contraseña
# ---------------------------------------------------------------------------


def _con_store_vacio():
    """Sustituye el store de alcances por uno sin cliente (Valkey ausente).

    El del plano de datos es *best effort* por diseño, así que no tener Valkey
    no puede cambiar lo que responde el endpoint — y estos tests miran el otro
    plano, el del proveedor.
    """
    from app.api.deps import get_scope_store
    from app.services.scope_store import ScopeStore

    fastapi_app.dependency_overrides[get_scope_store] = lambda: ScopeStore(None)


def test_cambiar_contrasena_cierra_las_demas_sesiones(
    client, db_session, test_organization_data, idp_falso
):
    """
    Es el agujero que este cambio cierra: hasta la v1.30.1, cambiar la
    contraseña no cerraba nada y el refresh token de este pool vale 90 días.
    Quien sospechaba que le habían robado la credencial cambiaba su contraseña y
    el intruso seguía renovando sesión durante meses.
    """
    user = _make_verified_user(db_session, test_organization_data)
    _con_store_vacio()

    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
    ):
        response = client.patch(
            "/api/v1/auth/password",
            headers={"Authorization": "Bearer lo-que-sea"},
            json={"old_password": "la-de-antes", "new_password": "La-nueva-1!"},
        )

    assert response.status_code == status.HTTP_200_OK
    idp_falso.revocar_sesiones_de.assert_called_once_with(handle=user.external_id)


def test_cambiar_contrasena_no_echa_a_quien_la_cambia(
    client, db_session, test_organization_data, idp_falso
):
    """La revocación no distingue tu dispositivo del de nadie, así que el
    endpoint abre una sesión nueva —después de revocar— y la devuelve. Sin esto,
    hacer lo correcto te cuesta volver a entrar.
    """
    user = _make_verified_user(db_session, test_organization_data)
    _con_store_vacio()

    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
    ):
        response = client.patch(
            "/api/v1/auth/password",
            headers={"Authorization": "Bearer lo-que-sea"},
            json={"old_password": "la-de-antes", "new_password": "La-nueva-1!"},
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["access_token"] == "access"
    # Y la sesión nueva se pide DESPUÉS de revocar, o caería con las demás.
    llamadas = [c[0] for c in idp_falso.method_calls]
    assert llamadas.index("revocar_sesiones_de") < llamadas.index("autenticar", 1)


def test_si_la_sesion_nueva_falla_la_contrasena_igual_cambio(
    client, db_session, test_organization_data, idp_falso
):
    """Reautenticar es una comodidad, no el objetivo. Si falla, la contraseña ya
    cambió y las sesiones ya se cortaron: se responde 200 sin credenciales y el
    cliente manda a iniciar sesión.
    """
    from app.services.identity import ErrorDelProveedor

    user = _make_verified_user(db_session, test_organization_data)
    _con_store_vacio()
    # La primera autenticación valida la contraseña actual; la segunda es la que
    # abre la sesión nueva.
    idp_falso.autenticar.side_effect = [
        Sesion(access_token="access"),
        ErrorDelProveedor("cayó", codigo="TooManyRequests"),
    ]

    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
    ):
        response = client.patch(
            "/api/v1/auth/password",
            headers={"Authorization": "Bearer lo-que-sea"},
            json={"old_password": "la-de-antes", "new_password": "La-nueva-1!"},
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["access_token"] is None
    idp_falso.revocar_sesiones_de.assert_called_once()


def test_si_la_revocacion_falla_el_endpoint_no_finge_que_todo_fue_bien(
    client, db_session, test_organization_data, idp_falso
):
    """La contraseña ya está cambiada, así que callarse sería mentir sobre lo
    que se consiguió. Se dice, y se dice qué hacer.
    """
    from app.services.identity import ErrorDelProveedor

    user = _make_verified_user(db_session, test_organization_data)
    _con_store_vacio()
    idp_falso.revocar_sesiones_de.side_effect = ErrorDelProveedor(
        "no se pudo", codigo="TooManyRequests"
    )

    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
    ):
        response = client.patch(
            "/api/v1/auth/password",
            headers={"Authorization": "Bearer lo-que-sea"},
            json={"old_password": "la-de-antes", "new_password": "La-nueva-1!"},
        )

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "cerrar las sesiones anteriores" in response.json()["detail"]


def test_restablecer_contrasena_cierra_las_demas_sesiones(
    client, db_session, test_user_data, idp_falso
):
    """Quien llega por aquí suele haber perdido el acceso, y a veces porque
    alguien más lo tiene. Sin revocar, el restablecimiento es cosmético.
    """
    codigo = "123456"
    db_session.add(
        TokenConfirmacion(
            id=uuid4(),
            token=codigo,
            expires_at=utcnow() + timedelta(hours=1),
            used=False,
            type=TokenType.PASSWORD_RESET,
            user_id=test_user_data.id,
            email=test_user_data.email,
        )
    )
    db_session.commit()
    _con_store_vacio()

    response = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": test_user_data.email,
            "code": codigo,
            "new_password": "La-nueva-1!",
        },
    )

    assert response.status_code == status.HTTP_200_OK
    idp_falso.fijar_password.assert_called_once()
    idp_falso.revocar_sesiones_de.assert_called_once_with(
        handle=test_user_data.external_id
    )


# ── /auth/refresh · el token rotado ──────────────────────────────────────
#
# Cognito sabe rotar refresh tokens y en este pool está apagado
# (`RefreshTokenRotation: null`). El día que se encienda devolverá uno nuevo en
# cada renovación y el anterior dejará de valer pasado el periodo de gracia. El
# endpoint tiene que reenviarlo **antes** de que eso pase: si no, todo el mundo
# acaba en la pantalla de login. Por eso estos dos tests son el paso 1 del orden
# de §24 y no van después de activar la rotación.


def test_refresh_reenvia_el_token_rotado(client, idp_falso):
    """Si el proveedor devuelve un refresh token nuevo, el cliente lo recibe."""
    idp_falso.renovar.return_value = Sesion(
        access_token="access-nuevo",
        id_token="id-nuevo",
        refresh_token="refresh-rotado",
        expires_in=3600,
    )

    response = client.post(
        "/api/v1/auth/refresh",
        json={"email": "usuario@example.com", "refresh_token": "refresh-viejo"},
    )

    assert response.status_code == status.HTTP_200_OK
    cuerpo = response.json()
    assert cuerpo["refresh_token"] == "refresh-rotado"
    assert cuerpo["access_token"] == "access-nuevo"
    idp_falso.renovar.assert_called_once_with(
        handle="usuario@example.com", refresh_token="refresh-viejo"
    )


def test_refresh_sin_rotacion_devuelve_el_campo_nulo(client, idp_falso):
    """Es el comportamiento de hoy, y tiene que seguir siendo válido.

    Sin rotación Cognito no manda `RefreshToken`, así que el campo sale `null`
    en vez de ausente o vacío: el cliente distingue «no hay uno nuevo» de «toma
    éste» sin adivinar. `nexus-web` ya lo trata así — `setSession()` guarda el
    token sólo si viene.
    """
    idp_falso.renovar.return_value = Sesion(
        access_token="access-nuevo",
        id_token="id-nuevo",
        refresh_token=None,
        expires_in=3600,
    )

    response = client.post(
        "/api/v1/auth/refresh",
        json={"email": "usuario@example.com", "refresh_token": "refresh-viejo"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["refresh_token"] is None

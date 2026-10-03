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

Desde la rebanada B3, `/auth/login` y `/auth/register` ya no dependen de
`get_identity_provider` a secas: dependen de `get_identity_provider_para_login`,
que resuelve la marca de la petición y enruta con `proveedor_para_cuenta()`.
El fixture `idp_falso` sustituye las dos, para que el doble valga tanto para
estos dos endpoints como para el resto (password, logout, etc.) sin que cada
test tenga que saber cuál usa cuál.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_identity_provider, get_identity_provider_para_login
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
    fastapi_app.dependency_overrides[get_identity_provider_para_login] = lambda: doble
    yield doble
    fastapi_app.dependency_overrides.pop(get_identity_provider, None)
    fastapi_app.dependency_overrides.pop(get_identity_provider_para_login, None)


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


def test_verify_email_usa_el_proveedor_de_la_marca_del_usuario(
    client, db_session, test_organization_data
):
    """
    El Flujo A (master con `password_temp`) crea la credencial y le fija la
    contraseña en Cognito. Para un master con `brand_account_id`, eso tiene
    que pasar en el pool de SU marca, no en el del despliegue — el mismo
    hueco que B3 ya cerró en login/register, aquí para verify-email.
    """
    from app.models.user import User

    marca = _marca_verificada(db_session, "meromero.com")

    user = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        email="master-mero-mero@example.com",
        full_name="Master de Mero Mero",
        is_master=True,
        email_verified=False,
        external_id=str(uuid4()),
        brand_account_id=marca.id,
    )
    db_session.add(user)
    db_session.flush()

    token_value = "verify-marca"
    token_record = TokenConfirmacion(
        id=uuid4(),
        token=token_value,
        expires_at=utcnow() + timedelta(hours=1),
        used=False,
        type=TokenType.EMAIL_VERIFICATION,
        user_id=user.id,
        email=user.email,
        password_temp="TempPass123!",
    )
    db_session.add(token_record)
    db_session.commit()

    proveedor_de_marca = MagicMock(spec=IdentityProvider)
    proveedor_de_marca.sujeto_de.return_value = None
    proveedor_de_marca.crear_credencial.return_value = str(uuid4())

    with patch(
        "app.api.v1.endpoints.auth.proveedor_para_cuenta",
        return_value=proveedor_de_marca,
    ) as resolver:
        response = client.post(f"/api/v1/auth/verify-email?token={token_value}")

    assert response.status_code == status.HTTP_200_OK
    resolver.assert_called_once()
    assert resolver.call_args.args[0].id == marca.id
    proveedor_de_marca.crear_credencial.assert_called_once()
    proveedor_de_marca.fijar_password.assert_called_once()


# ---------------------------------------------------------------------------
# Data token adjunto al login (Fase 1)
# ---------------------------------------------------------------------------


def _make_verified_user(db_session, test_organization_data):
    from app.models.organization_user import OrganizationRole, OrganizationUser
    from app.models.user import User

    user = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        email="login-datatoken@example.com",
        full_name="Login Test",
        email_verified=True,
        is_master=True,
        cognito_sub=str(uuid4()),
    )
    db_session.add(user)
    db_session.flush()
    # La membresía real, no sólo users.organization_id — get_current_user_full
    # falla cerrado sin ella desde el rediseño de DELETE (ver app/api/deps.py,
    # _load_current_user).
    db_session.add(
        OrganizationUser(
            organization_id=test_organization_data.id,
            user_id=user.id,
            role=OrganizationRole.OWNER.value,
        )
    )
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
        default_organization_id=test_organization_data.id,
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
# Resolución de marca en login y registro (Fase 3, rebanada B3)
# ---------------------------------------------------------------------------


def _marca_verificada(db_session, hostname, *, nombre="Mero Mero"):
    """Una `Account` de marca con su `tenant_domains` ya verificado.

    Minimal a propósito: estos tests no miran branding ni `account_path`, así
    que no hace falta `TenantBranding` ni el camino que sí necesita
    `tests/test_tenancy_codigo.py` para sus pruebas de techo descendente.
    """
    from app.models.account import Account
    from app.models.tenancy import TenantDomain
    from app.utils.datetime import utcnow

    cuenta = Account(id=uuid4(), name=nombre, status="ACTIVE")
    db_session.add(cuenta)
    db_session.flush()
    db_session.add(
        TenantDomain(
            account_id=cuenta.id,
            hostname=hostname,
            is_primary=True,
            status="VERIFIED",
            verified_at=utcnow(),
        )
    )
    db_session.commit()
    return cuenta


def test_login_sin_host_conocido_cae_en_la_marca_por_defecto(
    client, db_session, test_organization_data, idp_falso
):
    """
    Es el caso de el 100% del tráfico hoy: ningún `tenant_domains` verificado
    en producción, y `nexus-web-page` llama con una URL absoluta, así que el
    `Host` que ve esta API nunca es el de un partner. El comportamiento tiene
    que seguir siendo exactamente el de antes de B3.
    """
    user = _make_verified_user(db_session, test_organization_data)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "irrelevante"},
    )

    assert response.status_code == status.HTTP_200_OK


def test_login_filtra_por_marca_cuando_el_host_resuelve(
    client, db_session, test_organization_data, idp_falso
):
    """
    Dos filas, mismo correo, marcas distintas — lo que permiten los índices
    parciales de la migración `028` (ver
    `test_identidad_codigo.py::test_dos_marcas_pueden_compartir_correo` para
    la misma garantía al nivel del modelo). El login con el `Host` de Mero
    Mero tiene que autenticar a SU fila, no a la de la marca por defecto.
    """
    from app.models.user import User

    marca = _marca_verificada(db_session, "meromero.com")

    handle_default = str(uuid4())
    user_default = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        email="compartido@example.com",
        full_name="Marca por defecto",
        email_verified=True,
        external_id=handle_default,
        cognito_sub=str(uuid4()),
    )
    handle_marca = str(uuid4())
    user_marca = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        email="compartido@example.com",
        full_name="Usuario de Mero Mero",
        email_verified=True,
        external_id=handle_marca,
        cognito_sub=str(uuid4()),
        brand_account_id=marca.id,
    )
    db_session.add_all([user_default, user_marca])
    db_session.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "compartido@example.com", "password": "irrelevante"},
        headers={"Host": "meromero.com"},
    )

    assert response.status_code == status.HTTP_200_OK
    idp_falso.autenticar.assert_called_once_with(
        handle=handle_marca, password="irrelevante"
    )


def _datos_registro(**overrides):
    datos = {
        "account_name": "Mi Empresa",
        "email": "nuevo@example.com",
        "password": "Contrasena-larga1",
    }
    datos.update(overrides)
    return datos


def test_register_fija_brand_account_id_null_hoy(client, db_session, idp_falso):
    """
    El test que pide el propio documento de arquitectura (§26): fijar hoy
    que un alta sin `Host` de marca nace con `brand_account_id is None`, para
    que el día que cambie sea una decisión y no un descubrimiento.
    """
    from app.models.user import User

    idp_falso.crear_credencial.return_value = str(uuid4())

    response = client.post("/api/v1/auth/register", json=_datos_registro())

    assert response.status_code == status.HTTP_201_CREATED
    user = db_session.query(User).filter(User.email == "nuevo@example.com").first()
    assert user.brand_account_id is None


def test_register_asigna_la_marca_resuelta(client, db_session, idp_falso):
    """Con el `Host` de un partner verificado, el alta nueva nace en su marca."""
    from app.models.user import User

    marca = _marca_verificada(db_session, "meromero.com")
    idp_falso.crear_credencial.return_value = str(uuid4())

    response = client.post(
        "/api/v1/auth/register",
        json=_datos_registro(email="nuevo-mero-mero@example.com"),
        headers={"Host": "meromero.com"},
    )

    assert response.status_code == status.HTTP_201_CREATED
    user = (
        db_session.query(User)
        .filter(User.email == "nuevo-mero-mero@example.com")
        .first()
    )
    assert user.brand_account_id == marca.id


def test_register_el_duplicado_es_por_marca_no_global(client, db_session, idp_falso):
    """
    El mismo correo puede registrarse bajo dos marcas distintas sin 400 — es
    la consecuencia directa de que la unicidad ya es `(brand_account_id,
    email)` y no `email` a secas.
    """
    _marca_verificada(db_session, "meromero.com")
    # Un `sub` distinto por alta, como haría el Cognito real — un
    # `return_value` fijo chocaría con `ix_users_cognito_sub` al segundo
    # registro y el fallo sería del doble, no del código bajo prueba.
    idp_falso.crear_credencial.side_effect = lambda **_: str(uuid4())

    primero = client.post(
        "/api/v1/auth/register",
        json=_datos_registro(email="repetido@example.com"),
    )
    assert primero.status_code == status.HTTP_201_CREATED

    segundo = client.post(
        "/api/v1/auth/register",
        json=_datos_registro(email="repetido@example.com", account_name="Otra Empresa"),
        headers={"Host": "meromero.com"},
    )
    assert segundo.status_code == status.HTTP_201_CREATED

    tercero = client.post(
        "/api/v1/auth/register",
        json=_datos_registro(email="repetido@example.com", account_name="Otra Mas"),
    )
    assert tercero.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# Filtrado por marca en forgot/reset-password y resend-verification
#
# La rebanada B3 dejó fichado este hueco sin cerrarlo: los tres buscaban al
# usuario por `email` a secas, así que dos marcas compartiendo correo (lo que
# el índice parcial de la 028 ya permite) podían mezclar las filas.
# ---------------------------------------------------------------------------


def _dos_usuarios_mismo_correo(db_session, test_organization_data, marca, **extra):
    """Dos filas, mismo correo, una en la marca por defecto y otra en `marca`.

    Espejo de la fixture inline que ya usan los tests de login/register por
    marca — se repite en vez de extraerse porque cada endpoint necesita
    campos ligeramente distintos (`cognito_sub`, `is_master`).
    """
    from app.models.user import User

    user_default = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        email="compartido@example.com",
        full_name="Marca por defecto",
        external_id=str(uuid4()),
        **extra,
    )
    user_marca = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        email="compartido@example.com",
        full_name="Usuario de Mero Mero",
        external_id=str(uuid4()),
        brand_account_id=marca.id,
        **extra,
    )
    db_session.add_all([user_default, user_marca])
    db_session.commit()
    return user_default, user_marca


def test_forgot_password_filtra_por_marca_cuando_el_host_resuelve(
    client, db_session, test_organization_data
):
    """El código de recuperación tiene que generarse para la fila de la marca
    que resolvió el `Host`, no para la primera que encuentre el query.
    """
    marca = _marca_verificada(db_session, "meromero.com")
    _, user_marca = _dos_usuarios_mismo_correo(
        db_session, test_organization_data, marca, email_verified=True
    )

    with patch(
        "app.api.v1.endpoints.auth.send_password_reset_email", return_value=True
    ):
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "compartido@example.com"},
            headers={"Host": "meromero.com"},
        )

    assert response.status_code == status.HTTP_200_OK
    token_record = (
        db_session.query(TokenConfirmacion)
        .filter(TokenConfirmacion.type == TokenType.PASSWORD_RESET)
        .one()
    )
    assert token_record.user_id == user_marca.id


def test_resend_verification_filtra_por_marca_cuando_el_host_resuelve(
    client, db_session, test_organization_data
):
    """Mismo criterio que forgot-password: el reenvío es para la fila de la
    marca resuelta, no para cualquiera con ese correo.
    """
    marca = _marca_verificada(db_session, "meromero.com")
    _, user_marca = _dos_usuarios_mismo_correo(
        db_session, test_organization_data, marca, email_verified=False
    )

    with patch("app.api.v1.endpoints.auth.send_verification_email", return_value=True):
        response = client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "compartido@example.com"},
            headers={"Host": "meromero.com"},
        )

    assert response.status_code == status.HTTP_200_OK
    token_record = (
        db_session.query(TokenConfirmacion)
        .filter(TokenConfirmacion.type == TokenType.EMAIL_VERIFICATION)
        .one()
    )
    assert token_record.user_id == user_marca.id


def test_reset_password_no_cruza_marcas_con_el_mismo_correo(
    client, db_session, test_organization_data, idp_falso
):
    """
    El bug real, más fino que «filtra por marca»: el `user` se buscaba por un
    lado y el `token_record` por otro, cada uno con su propio filtro por
    `email`. Con dos marcas compartiendo correo, un código emitido para la
    fila de Mero Mero resolvía igual el `user` de la marca por defecto —y le
    cambiaba la contraseña a ESA, no a la dueña del código.
    """
    marca = _marca_verificada(db_session, "meromero.com")
    user_default, user_marca = _dos_usuarios_mismo_correo(
        db_session, test_organization_data, marca, email_verified=True
    )

    codigo = "654321"
    db_session.add(
        TokenConfirmacion(
            id=uuid4(),
            token=codigo,
            expires_at=utcnow() + timedelta(hours=1),
            used=False,
            type=TokenType.PASSWORD_RESET,
            user_id=user_marca.id,
            email=user_marca.email,
        )
    )
    db_session.commit()
    _con_store_vacio()

    # Sin el Host de Mero Mero, el código resuelve a la marca por defecto —y
    # ese código no es el suyo: 400, no un cambio silencioso a la fila
    # equivocada.
    sin_host = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "compartido@example.com",
            "code": codigo,
            "new_password": "La-nueva-1!",
        },
    )
    assert sin_host.status_code == status.HTTP_400_BAD_REQUEST
    idp_falso.fijar_password.assert_not_called()

    # Con el Host correcto, el mismo código sí restablece la fila de Mero Mero.
    con_host = client.post(
        "/api/v1/auth/reset-password",
        json={
            "email": "compartido@example.com",
            "code": codigo,
            "new_password": "La-nueva-1!",
        },
        headers={"Host": "meromero.com"},
    )
    assert con_host.status_code == status.HTTP_200_OK
    # `assert_called_once_with` sobre las DOS llamadas acumuladas: la primera
    # no llamó a nadie (400 antes de llegar al proveedor), así que la única
    # llamada real tiene que ser con el handle de Mero Mero, nunca con el de
    # la marca por defecto.
    idp_falso.fijar_password.assert_called_once_with(
        handle=user_marca.external_id, password="La-nueva-1!"
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


# ---------------------------------------------------------------------------
# Proveedor por marca en endpoints autenticados (post-B3)
#
# `current_user` ya está autenticado, así que su `brand_account_id` no
# depende de ningún `Host` — se resuelve directo de la fila, no de la
# petición. Sin esto, un master de una marca con Cognito propio seguiría
# hablándole al pool por defecto al cambiar su contraseña o cerrar sesión.
# ---------------------------------------------------------------------------


def test_cambiar_contrasena_usa_el_proveedor_de_la_marca_del_usuario(
    client, db_session, test_organization_data
):
    marca = _marca_verificada(db_session, "meromero.com")
    user = _make_verified_user(db_session, test_organization_data)
    user.brand_account_id = marca.id
    db_session.commit()
    _con_store_vacio()

    proveedor_de_marca = MagicMock(spec=IdentityProvider)
    proveedor_de_marca.autenticar.return_value = Sesion(access_token="access-marca")

    with (
        patch(
            "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
        ),
        patch(
            "app.api.v1.endpoints.auth.proveedor_para_cuenta",
            return_value=proveedor_de_marca,
        ) as resolver,
    ):
        response = client.patch(
            "/api/v1/auth/password",
            headers={"Authorization": "Bearer lo-que-sea"},
            json={"old_password": "la-de-antes", "new_password": "La-nueva-1!"},
        )

    assert response.status_code == status.HTTP_200_OK
    resolver.assert_called_once()
    assert resolver.call_args.args[0].id == marca.id
    proveedor_de_marca.fijar_password.assert_called_once()
    proveedor_de_marca.revocar_sesiones_de.assert_called_once()


def test_logout_usa_el_proveedor_de_la_marca_del_usuario(
    client, db_session, test_organization_data
):
    marca = _marca_verificada(db_session, "meromero.com")
    user = _make_verified_user(db_session, test_organization_data)
    user.brand_account_id = marca.id
    db_session.commit()
    _con_store_vacio()

    proveedor_de_marca = MagicMock(spec=IdentityProvider)

    with (
        patch(
            "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
        ),
        patch(
            "app.api.v1.endpoints.auth.proveedor_para_cuenta",
            return_value=proveedor_de_marca,
        ) as resolver,
    ):
        response = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": "Bearer lo-que-sea"},
        )

    assert response.status_code == status.HTTP_200_OK
    resolver.assert_called_once()
    assert resolver.call_args.args[0].id == marca.id
    proveedor_de_marca.revocar_sesiones.assert_called_once_with(
        access_token="lo-que-sea"
    )


# ---------------------------------------------------------------------------
# Selector de cuenta — organización activa de la sesión (B3, §26)
#
# Medido contra producción el 02/10/2026: cero usuarios con más de una
# membresía activa hoy. Estos tests construyen el caso a mano porque ningún
# dato real lo produce todavía.
# ---------------------------------------------------------------------------


def _con_segunda_organizacion(db_session, test_organization_data, user, nombre):
    from app.models.organization import Organization
    from app.models.organization_user import OrganizationRole, OrganizationUser

    segunda_org = Organization(
        id=uuid4(),
        account_id=test_organization_data.account_id,
        name=nombre,
        status="ACTIVE",
    )
    db_session.add(segunda_org)
    db_session.flush()
    db_session.add(
        OrganizationUser(
            organization_id=segunda_org.id,
            user_id=user.id,
            role=OrganizationRole.MEMBER.value,
        )
    )
    db_session.commit()
    return segunda_org


def test_list_my_organizations_una_sola_membresia(
    client, db_session, test_organization_data
):
    """El caso de todo el mundo hoy: una fila, nada que elegir."""
    user = _make_verified_user(db_session, test_organization_data)

    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
    ):
        response = client.get(
            "/api/v1/auth/organizations",
            headers={"Authorization": "Bearer lo-que-sea"},
        )

    assert response.status_code == status.HTTP_200_OK
    cuerpo = response.json()
    assert len(cuerpo) == 1
    assert cuerpo[0]["organization_id"] == str(test_organization_data.id)
    assert cuerpo[0]["role"] == "owner"


def test_list_my_organizations_con_dos_membresias(
    client, db_session, test_organization_data
):
    user = _make_verified_user(db_session, test_organization_data)
    segunda_org = _con_segunda_organizacion(
        db_session, test_organization_data, user, "Flota Norte"
    )

    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
    ):
        response = client.get(
            "/api/v1/auth/organizations",
            headers={"Authorization": "Bearer lo-que-sea"},
        )

    assert response.status_code == status.HTTP_200_OK
    orgs = {fila["organization_id"]: fila["role"] for fila in response.json()}
    assert orgs == {
        str(test_organization_data.id): "owner",
        str(segunda_org.id): "member",
    }


def test_x_organization_id_cambia_la_organizacion_activa(
    client, db_session, test_organization_data
):
    """El selector de verdad: con dos membresías activas, la cabecera
    `X-Organization-Id` decide con cuál actúa la sesión — y `/auth/me` lo
    refleja sin que el endpoint sepa nada de selectores."""
    user = _make_verified_user(db_session, test_organization_data)
    segunda_org = _con_segunda_organizacion(
        db_session, test_organization_data, user, "Flota Norte"
    )

    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
    ):
        por_defecto = client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer lo-que-sea"}
        )
        con_cabecera = client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": "Bearer lo-que-sea",
                "X-Organization-Id": str(segunda_org.id),
            },
        )

    assert por_defecto.status_code == status.HTTP_200_OK
    assert con_cabecera.status_code == status.HTTP_200_OK
    assert por_defecto.json()["organization_id"] == str(test_organization_data.id)
    assert con_cabecera.json()["organization_id"] == str(segunda_org.id)
    assert con_cabecera.json()["role"] == "member"


def test_x_organization_id_ajena_falla_cerrado(
    client, db_session, test_organization_data
):
    """Pedir una organización de la que no se es miembro activo es un 403,
    no una fuga a datos ajenos."""
    from app.models.organization import Organization

    user = _make_verified_user(db_session, test_organization_data)
    org_ajena = Organization(
        id=uuid4(),
        account_id=test_organization_data.account_id,
        name="No es la mía",
        status="ACTIVE",
    )
    db_session.add(org_ajena)
    db_session.commit()

    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
    ):
        response = client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": "Bearer lo-que-sea",
                "X-Organization-Id": str(org_ajena.id),
            },
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN

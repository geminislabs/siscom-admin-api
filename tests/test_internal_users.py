"""La superficie interna de usuarios — la que usa GAC.

Existe por una razon concreta, y estos tests la fijan: **los huerfanos no se
pueden tocar por la via de Nexus**. Su `organization_id` apunta a una
organizacion que no existe, asi que `DELETE /organizations/{org}/users/{id}`
falla en `_verify_org_access` antes de llegar al usuario — el endpoint que
existe justo para desactivar gente no puede desactivarlos.

Al 21/09/2026 son siete de veintitres usuarios en produccion.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import AuthResult, get_identity_provider
from app.api.v1.endpoints.internal import users as internal_users
from app.main import app as fastapi_app
from app.models.user import User, UserStatus
from app.services.identity import ErrorDelProveedor, IdentityProvider


@pytest.fixture
def como_gac():
    """Sustituye la autenticacion PASETO por un token de servicio de GAC."""
    fastapi_app.dependency_overrides[internal_users.get_auth_for_internal_users] = (
        lambda: AuthResult(
            auth_type="paseto",
            payload={"service": "gac", "role": "GAC_ADMIN"},
        )
    )
    yield
    fastapi_app.dependency_overrides.pop(
        internal_users.get_auth_for_internal_users, None
    )


@pytest.fixture
def sin_fk_de_organizacion(db_session):
    """Quita `users_organization_id_fkey` para poder construir un huerfano.

    **El harness es mas estricto que produccion, y por eso hace falta esto.**
    El modelo declara `ForeignKey("organizations.id")` y `create_all()` la crea;
    el esquema productivo **no la tiene** — solo un indice, `idx_users_org_master`.
    Es deriva conocida, anotada al desplegar la `v1.32.2`, y el comparador no la
    ve porque mira columnas y no restricciones.

    La consecuencia practica es incomoda y conviene no esconderla: sin este
    `DROP`, el caso que este endpoint existe para resolver **no se puede
    escribir como test**, porque la base de pruebas lo prohibe y la de verdad lo
    contiene siete veces.

    El `DROP` vive dentro de la transaccion del test —el DDL de Postgres es
    transaccional— asi que se revierte solo al terminar. Y el dia que la FK
    entre en produccion (punto 3 de la cola), esto fallara y sera la señal
    correcta: los huerfanos habran dejado de ser posibles.
    """
    from sqlalchemy import text

    db_session.execute(
        text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_organization_id_fkey")
    )
    db_session.flush()
    yield


@pytest.fixture
def idp_falso():
    doble = MagicMock(spec=IdentityProvider)
    fastapi_app.dependency_overrides[get_identity_provider] = lambda: doble
    yield doble
    fastapi_app.dependency_overrides.pop(get_identity_provider, None)


def _usuario(db_session, organization_id, correo, estado=UserStatus.ACTIVE):
    user = User(
        id=uuid4(),
        organization_id=organization_id,
        cognito_sub=f"sub-{correo}",
        external_id=correo,
        email=correo,
        full_name="Quien Sea",
        is_master=False,
        status=estado.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _huerfano(db_session, correo, estado=UserStatus.ACTIVE):
    """Un usuario cuya organizacion no existe.

    Se puede construir porque `users.organization_id` **no tiene clave foranea
    en produccion**, que es exactamente la deriva que produjo los siete. El
    harness reproduce esa forma a proposito: si algun dia se anade la FK, este
    helper dejara de funcionar y el test avisara de que el mundo cambio.
    """
    return _usuario(db_session, uuid4(), correo, estado)


# ── Listar ───────────────────────────────────────────────────────────────


def test_orphaned_devuelve_solo_a_los_que_nexus_no_alcanza(
    authenticated_client,
    db_session,
    test_organization_data,
    como_gac,
    sin_fk_de_organizacion,
):
    normal = _usuario(db_session, test_organization_data.id, "normal@example.com")
    perdido = _huerfano(db_session, "huerfano@example.com")

    respuesta = authenticated_client.get("/api/v1/internal/users?orphaned=true")

    assert respuesta.status_code == status.HTTP_200_OK
    ids = {fila["id"] for fila in respuesta.json()}
    assert str(perdido.id) in ids
    assert str(normal.id) not in ids


def test_la_lista_marca_quien_es_huerfano(
    authenticated_client,
    db_session,
    test_organization_data,
    como_gac,
    sin_fk_de_organizacion,
):
    """Sin este booleano, GAC no distingue un usuario normal de uno huerfano
    sin consultar otra tabla — y son justo los que necesita ver."""
    _usuario(db_session, test_organization_data.id, "conorg@example.com")
    _huerfano(db_session, "sinorg@example.com")

    filas = authenticated_client.get("/api/v1/internal/users?limit=200").json()
    por_correo = {f["email"]: f for f in filas}

    assert por_correo["conorg@example.com"]["huerfano"] is False
    assert por_correo["sinorg@example.com"]["huerfano"] is True


def test_se_puede_filtrar_por_estado(
    authenticated_client, db_session, test_organization_data, como_gac
):
    _usuario(db_session, test_organization_data.id, "activo@example.com")
    _usuario(
        db_session,
        test_organization_data.id,
        "inactivo@example.com",
        UserStatus.INACTIVE,
    )

    filas = authenticated_client.get(
        "/api/v1/internal/users?status=INACTIVE&limit=200"
    ).json()
    correos = {f["email"] for f in filas}

    assert "inactivo@example.com" in correos
    assert "activo@example.com" not in correos


# ── Cambiar estado ───────────────────────────────────────────────────────


def test_se_puede_desactivar_a_un_huerfano(
    authenticated_client, db_session, como_gac, idp_falso, sin_fk_de_organizacion
):
    """**El test que justifica todo el endpoint.**

    Este mismo usuario, por la via de Nexus, es inalcanzable: su organizacion
    no existe y la comprobacion de acceso falla antes de mirarlo.
    """
    perdido = _huerfano(db_session, "fer@example.com")

    respuesta = authenticated_client.patch(
        f"/api/v1/internal/users/{perdido.id}/status",
        json={"status": "INACTIVE", "motivo": "huerfano de la 029"},
    )

    assert respuesta.status_code == status.HTTP_200_OK
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "INACTIVE"
    assert cuerpo["proveedor_sincronizado"] is True
    db_session.refresh(perdido)
    assert perdido.status == UserStatus.INACTIVE.value
    idp_falso.deshabilitar.assert_called_once_with(handle="fer@example.com")


def test_reactivar_vuelve_a_habilitar_la_credencial(
    authenticated_client, db_session, test_organization_data, como_gac, idp_falso
):
    usuario = _usuario(
        db_session,
        test_organization_data.id,
        "vuelve@example.com",
        UserStatus.INACTIVE,
    )

    respuesta = authenticated_client.patch(
        f"/api/v1/internal/users/{usuario.id}/status", json={"status": "ACTIVE"}
    )

    assert respuesta.status_code == status.HTTP_200_OK
    db_session.refresh(usuario)
    assert usuario.status == UserStatus.ACTIVE.value
    idp_falso.habilitar.assert_called_once_with(handle="vuelve@example.com")


def test_poner_el_estado_que_ya_tiene_RECONCILIA_el_proveedor(
    authenticated_client, db_session, test_organization_data, como_gac, idp_falso
):
    """El inverso del test que vivio aqui hasta el 22/09/2026.

    Aquel afirmaba que un PATCH sin cambio de estado **no** tocaba el
    proveedor, para ahorrar trafico. El razonamiento confundia dos cosas:
    refrescar una pantalla es un GET, no un PATCH.

    Y el atajo tenia un fallo peor que el trafico que ahorraba: **cuando la
    fila y el proveedor divergen, era lo unico que podia reconciliarlos, y se
    negaba a intentarlo**. Ocurrio en produccion: seis bajas escribieron
    INACTIVE en la base y fallaron contra Cognito por un permiso de IAM que
    faltaba; al reintentar, el endpoint respondia "sin cambio, todo
    sincronizado" —falso— y hubo que rodearlo a mano con un ciclo
    ACTIVE/INACTIVE.
    """
    usuario = _usuario(db_session, test_organization_data.id, "igual@example.com")

    respuesta = authenticated_client.patch(
        f"/api/v1/internal/users/{usuario.id}/status", json={"status": "ACTIVE"}
    )

    assert respuesta.status_code == status.HTTP_200_OK
    idp_falso.habilitar.assert_called_once_with(handle="igual@example.com")
    assert respuesta.json()["proveedor_sincronizado"] is True


def test_reconciliar_reporta_el_fallo_en_vez_de_esconderlo(
    authenticated_client, db_session, test_organization_data, como_gac, idp_falso
):
    """El caso exacto de produccion: la fila ya esta INACTIVE, el proveedor no.

    Antes esto respondia `proveedor_sincronizado: true` sin preguntar. Ahora
    intenta, falla, y **lo dice** — que es lo unico que permite saber que
    quedan credenciales vivas.
    """
    usuario = _usuario(
        db_session,
        test_organization_data.id,
        "divergente@example.com",
        UserStatus.INACTIVE,
    )
    idp_falso.deshabilitar.side_effect = ErrorDelProveedor(
        codigo="AccessDeniedException", mensaje="no autorizado a AdminDisableUser"
    )

    respuesta = authenticated_client.patch(
        f"/api/v1/internal/users/{usuario.id}/status", json={"status": "INACTIVE"}
    )

    assert respuesta.status_code == status.HTTP_200_OK
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "INACTIVE"
    assert cuerpo["proveedor_sincronizado"] is False
    assert "AdminDisableUser" in cuerpo["detalle"]


def test_si_el_proveedor_falla_la_baja_se_mantiene_y_se_dice(
    authenticated_client, db_session, test_organization_data, como_gac, idp_falso
):
    """La fuente de verdad es `users.status` (§9, regla 1), asi que el fallo del
    proveedor no revierte nada. Pero **se informa**: devolverlo en vez de
    tragarselo es lo que permite a GAC enseñar «desactivado, pero la credencial
    sigue viva» en vez de mentir."""
    usuario = _usuario(db_session, test_organization_data.id, "falla@example.com")
    idp_falso.deshabilitar.side_effect = ErrorDelProveedor(
        codigo="InternalErrorException", mensaje="cayo"
    )

    respuesta = authenticated_client.patch(
        f"/api/v1/internal/users/{usuario.id}/status", json={"status": "INACTIVE"}
    )

    assert respuesta.status_code == status.HTTP_200_OK
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "INACTIVE"
    assert cuerpo["proveedor_sincronizado"] is False
    assert "no se pudo actualizar" in cuerpo["detalle"]
    db_session.refresh(usuario)
    assert usuario.status == UserStatus.INACTIVE.value


def test_un_estado_que_el_CHECK_no_admite_se_rechaza(
    authenticated_client, db_session, test_organization_data, como_gac, idp_falso
):
    """`SUSPENDED` no existe, y el esquema tiene que decirlo antes de que lo diga
    Postgres: la lista la fija `ck_users_status` y el enum es su gemelo."""
    usuario = _usuario(db_session, test_organization_data.id, "raro@example.com")

    respuesta = authenticated_client.patch(
        f"/api/v1/internal/users/{usuario.id}/status", json={"status": "SUSPENDED"}
    )

    assert respuesta.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_usuario_inexistente_da_404(authenticated_client, como_gac, idp_falso):
    respuesta = authenticated_client.patch(
        f"/api/v1/internal/users/{uuid4()}/status", json={"status": "INACTIVE"}
    )
    assert respuesta.status_code == status.HTTP_404_NOT_FOUND


def test_sin_token_no_se_entra(authenticated_client):
    """La mitad facil: sin cabecera, fuera."""
    respuesta = authenticated_client.get("/api/v1/internal/users")
    assert respuesta.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )


def test_un_usuario_normal_de_nexus_no_puede_listar(client, db_session, test_user_data):
    """La mitad que importa, y que estuvo mal escrita hasta el 22/09/2026.

    El test anterior mandaba la peticion **sin cabecera** y comprobaba el 401.
    Pasaba en verde sin probar nada: la pregunta no era "¿rechaza a quien no
    trae token?" sino "¿rechaza a quien trae **otro** token?".

    Y la respuesta era que no. `get_auth_cognito_or_paseto` intentaba Cognito
    primero y concedia acceso sin mirar ningun rol, asi que cualquiera que
    pudiera iniciar sesion en Nexus entraba en las veinte rutas de escritura
    del plano de control. Medido por ejecucion: un usuario normal recibia 200
    de PATCH /internal/users/{id}/status y dejaba a la victima en INACTIVE.
    """
    with patch(
        "app.api.deps.verify_cognito_token",
        return_value={"sub": test_user_data.cognito_sub},
    ):
        respuesta = client.get(
            "/api/v1/internal/users",
            headers={"Authorization": "Bearer token-valido-de-un-usuario-normal"},
        )

    assert respuesta.status_code == status.HTTP_403_FORBIDDEN


def test_un_usuario_normal_de_nexus_no_puede_desactivar_a_nadie(
    client, db_session, test_organization_data, test_user_data, idp_falso
):
    """El mismo hueco sobre la ruta que de verdad hace daño."""
    victima = _usuario(db_session, test_organization_data.id, "victima@example.com")

    with patch(
        "app.api.deps.verify_cognito_token",
        return_value={"sub": test_user_data.cognito_sub},
    ):
        respuesta = client.patch(
            f"/api/v1/internal/users/{victima.id}/status",
            headers={"Authorization": "Bearer token-valido-de-un-usuario-normal"},
            json={"status": "INACTIVE"},
        )

    assert respuesta.status_code == status.HTTP_403_FORBIDDEN
    db_session.refresh(victima)
    assert victima.status == UserStatus.ACTIVE.value
    idp_falso.deshabilitar.assert_not_called()

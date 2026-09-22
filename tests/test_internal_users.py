"""La superficie interna de usuarios — la que usa GAC.

Existe por una razon concreta, y estos tests la fijan: **los huerfanos no se
pueden tocar por la via de Nexus**. Su `organization_id` apunta a una
organizacion que no existe, asi que `DELETE /organizations/{org}/users/{id}`
falla en `_verify_org_access` antes de llegar al usuario — el endpoint que
existe justo para desactivar gente no puede desactivarlos.

Al 21/09/2026 son siete de veintitres usuarios en produccion.
"""

from unittest.mock import MagicMock
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


def test_poner_el_estado_que_ya_tiene_no_llama_al_proveedor(
    authenticated_client, db_session, test_organization_data, como_gac, idp_falso
):
    """Idempotente, y sin trafico de mas: `deshabilitar` y `habilitar` aguantan
    repeticiones, pero llamarlas de mas convierte cada refresco de una pantalla
    de GAC en peticiones contra Cognito."""
    usuario = _usuario(db_session, test_organization_data.id, "igual@example.com")

    respuesta = authenticated_client.patch(
        f"/api/v1/internal/users/{usuario.id}/status", json={"status": "ACTIVE"}
    )

    assert respuesta.status_code == status.HTTP_200_OK
    assert "Sin cambio" in respuesta.json()["detalle"]
    idp_falso.habilitar.assert_not_called()
    idp_falso.deshabilitar.assert_not_called()


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


def test_sin_token_de_gac_no_se_entra(authenticated_client, db_session):
    """Sin el override de autenticacion, la dependencia real tiene que rechazar.

    Es la mitad que no se puede olvidar: un endpoint que lista y desactiva
    usuarios del sistema entero, sin pasar por organizacion, es exactamente el
    que no puede quedarse abierto.
    """
    respuesta = authenticated_client.get("/api/v1/internal/users")
    assert respuesta.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )

"""El codigo que usa `users.status` — la mitad *contract* de la 029.

La migracion `029_estado_de_usuario` viajo sola en la `v1.32.2`: puso la
columna y no la leyo nadie. Esto es el release siguiente, el que cierra el
fallo vivo que la 029 describe:

  1. Un admin saca a alguien de la organizacion. Hasta ahora se borraba **la
     membresia** y la fila de `users` sobrevivia intacta, con su correo y su
     credencial.
  2. Meses despues lo vuelven a invitar: `invite_user` busca por correo,
     encuentra la fila y responde 400.
  3. No habia salida por la API — ningun endpoint borra usuarios, y no habia
     columna de estado. Solo se arreglaba con SQL a mano.

La salida no es borrar la fila: veinte claves foraneas referencian `users`,
varias en cascada hacia `mobility.devices`, `team.members`, `user_units` y
`user_devices`. Es **desactivarla y reactivarla**.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_identity_provider
from app.main import app as fastapi_app
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.token_confirmacion import TokenConfirmacion, TokenType
from app.models.user import User, UserStatus
from app.services.identity import ErrorDelProveedor, IdentityProvider
from app.utils.datetime import utcnow


@pytest.fixture
def idp_falso():
    doble = MagicMock(spec=IdentityProvider)
    doble.sujeto_de.return_value = None
    doble.crear_credencial.return_value = "sub-nuevo"
    fastapi_app.dependency_overrides[get_identity_provider] = lambda: doble
    yield doble
    fastapi_app.dependency_overrides.pop(get_identity_provider, None)


def _sacar_de_la_organizacion(client, actor, organizacion, victima):
    """DELETE con la identidad del actor.

    `require_organization_role` no se puede sustituir por
    `dependency_overrides`: es una *factory*, asi que el objeto que la ruta
    capturo al importarse no es el que devolveria otra llamada. Se entra por
    donde entra produccion —un token que `verify_cognito_token` valida— y el
    rol sale de la membresia, que es justo lo que este cambio deja como unica
    fuente.
    """
    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": actor.cognito_sub}
    ):
        return client.delete(
            f"/api/v1/organizations/{organizacion.id}/users/{victima.id}",
            headers={"Authorization": "Bearer lo-que-sea"},
        )


def _otro_usuario(db_session, organizacion, correo, rol=OrganizationRole.MEMBER):
    """Un segundo usuario con membresia, para poder sacarlo."""
    user = User(
        id=uuid4(),
        organization_id=organizacion.id,
        cognito_sub=f"sub-{correo}",
        external_id=correo,
        email=correo,
        full_name="Quien Sea",
        is_master=False,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        OrganizationUser(
            organization_id=organizacion.id, user_id=user.id, role=rol.value
        )
    )
    db_session.commit()
    db_session.refresh(user)
    return user


# ── La columna ───────────────────────────────────────────────────────────


def test_un_usuario_nace_activo(db_session, test_organization_data):
    """El `server_default` de la 029 vale para las filas que ya existian; este
    default vale para las que cree el codigo. Sin el, el harness —que construye
    el esquema con `create_all()`— insertaria NULL contra un NOT NULL."""
    user = _otro_usuario(db_session, test_organization_data, "nace@example.com")
    assert user.status == UserStatus.ACTIVE.value


# ── Baja ─────────────────────────────────────────────────────────────────


def test_sacar_de_la_organizacion_desactiva_la_fila(
    client, db_session, test_organization_data, test_user_data, idp_falso
):
    victima = _otro_usuario(db_session, test_organization_data, "baja@example.com")

    respuesta = _sacar_de_la_organizacion(
        client, test_user_data, test_organization_data, victima
    )

    assert respuesta.status_code == status.HTTP_204_NO_CONTENT
    db_session.refresh(victima)
    assert victima.status == UserStatus.INACTIVE.value
    # La fila sigue ahi: es lo que referencian las veinte FK.
    assert db_session.query(User).filter(User.id == victima.id).first() is not None
    # Y la membresia no.
    assert (
        db_session.query(OrganizationUser)
        .filter(OrganizationUser.user_id == victima.id)
        .first()
        is None
    )


def test_la_baja_deshabilita_la_credencial_por_su_handle(
    client, db_session, test_organization_data, test_user_data, idp_falso
):
    """El refuerzo en el proveedor va por `external_id`, no por el correo.

    Hoy coinciden; con handles UUID (rebanada B2) dejaran de coincidir, y
    mandar el correo deshabilitaria a otro o a nadie."""
    victima = _otro_usuario(db_session, test_organization_data, "handle@example.com")
    victima.external_id = "8f1d0c3e-uuid-como-handle"
    db_session.add(victima)
    db_session.commit()

    _sacar_de_la_organizacion(client, test_user_data, test_organization_data, victima)

    idp_falso.deshabilitar.assert_called_once_with(handle="8f1d0c3e-uuid-como-handle")


def test_si_el_proveedor_falla_la_baja_se_mantiene(
    client, db_session, test_organization_data, test_user_data, idp_falso
):
    """La fuente de verdad es `users.status`, no el proveedor (§9, regla 1).

    Si `admin_disable_user` falla queda una credencial habilitada que no
    autoriza nada, porque `deps.py` revalida contra Postgres en cada peticion.
    Al reves —deshabilitar y que el commit fallara— dejaria a alguien sin poder
    entrar y activo en la base, que es peor."""
    victima = _otro_usuario(db_session, test_organization_data, "falla@example.com")
    idp_falso.deshabilitar.side_effect = ErrorDelProveedor(
        codigo="InternalErrorException", mensaje="cayo"
    )

    respuesta = _sacar_de_la_organizacion(
        client, test_user_data, test_organization_data, victima
    )

    assert respuesta.status_code == status.HTTP_204_NO_CONTENT
    db_session.refresh(victima)
    assert victima.status == UserStatus.INACTIVE.value


# ── Readmision ───────────────────────────────────────────────────────────


def test_se_puede_reinvitar_a_quien_esta_inactivo(
    authenticated_client, db_session, test_organization_data
):
    """El 400 del callejon sin salida. Este es el test que describe el fallo
    que la 029 vino a destrabar."""
    ex = _otro_usuario(db_session, test_organization_data, "vuelve@example.com")
    ex.status = UserStatus.INACTIVE.value
    db_session.add(ex)
    db_session.commit()

    respuesta = authenticated_client.post(
        "/api/v1/users/invite",
        json={"email": "vuelve@example.com", "full_name": "Quien Vuelve"},
    )

    assert respuesta.status_code == status.HTTP_201_CREATED


def test_seguir_activo_sigue_bloqueando_la_invitacion(
    authenticated_client, db_session, test_organization_data
):
    """La otra mitad, y la que impide que esto sea un agujero: reinvitar a
    alguien que sigue activo tiene que seguir fallando."""
    _otro_usuario(db_session, test_organization_data, "activo@example.com")

    respuesta = authenticated_client.post(
        "/api/v1/users/invite",
        json={"email": "activo@example.com", "full_name": "Sigue Aqui"},
    )

    assert respuesta.status_code == status.HTTP_400_BAD_REQUEST


def test_aceptar_la_invitacion_reactiva_la_fila_y_no_crea_otra(
    client, db_session, test_organization_data, idp_falso
):
    """El corazon de la 029: **la misma fila**, con su id intacto.

    Crear otra no seria alternativa aunque se quisiera: los indices
    `uq_users_marca_correo` y `uq_users_correo_marca_por_defecto` de la 028 no
    filtran por estado, asi que Postgres rechazaria el INSERT."""
    ex = _otro_usuario(db_session, test_organization_data, "readmit@example.com")
    id_original = ex.id
    ex.status = UserStatus.INACTIVE.value
    db_session.add(ex)
    db_session.add(
        TokenConfirmacion(
            id=uuid4(),
            token="tok-readmision",
            organization_id=test_organization_data.id,
            email="readmit@example.com",
            full_name="Readmitido",
            expires_at=utcnow() + timedelta_una_hora(),
            used=False,
            type=TokenType.INVITATION,
        )
    )
    db_session.commit()
    idp_falso.sujeto_de.return_value = "sub-readmit@example.com"

    respuesta = client.post(
        "/api/v1/users/accept-invitation",
        json={"token": "tok-readmision", "password": "La-nueva-1!"},
    )

    assert respuesta.status_code == status.HTTP_201_CREATED
    filas = db_session.query(User).filter(User.email == "readmit@example.com").all()
    assert len(filas) == 1
    assert filas[0].id == id_original
    assert filas[0].status == UserStatus.ACTIVE.value
    # Y no se creo credencial nueva: la vieja se reabre.
    idp_falso.crear_credencial.assert_not_called()
    idp_falso.habilitar.assert_called_once_with(handle="readmit@example.com")


def test_la_readmision_usa_el_handle_de_la_fila_y_no_el_correo(
    client, db_session, test_organization_data, idp_falso
):
    """Con handles UUID el correo deja de servir para hablar con el proveedor.

    Reconstruirlo a partir del correo funcionaria hoy y se rompería en silencio
    con el primer handle UUID — el mismo fallo que la §24 midio en
    `/auth/refresh`."""
    ex = _otro_usuario(db_session, test_organization_data, "uuid@example.com")
    ex.status = UserStatus.INACTIVE.value
    ex.external_id = "3b9a-uuid-opaco"
    db_session.add(ex)
    db_session.add(
        TokenConfirmacion(
            id=uuid4(),
            token="tok-uuid",
            organization_id=test_organization_data.id,
            email="uuid@example.com",
            full_name=None,
            expires_at=utcnow() + timedelta_una_hora(),
            used=False,
            type=TokenType.INVITATION,
        )
    )
    db_session.commit()
    idp_falso.sujeto_de.return_value = "sub-uuid"

    respuesta = client.post(
        "/api/v1/users/accept-invitation",
        json={"token": "tok-uuid", "password": "La-nueva-1!"},
    )

    assert respuesta.status_code == status.HTTP_201_CREATED
    idp_falso.sujeto_de.assert_called_once_with(handle="3b9a-uuid-opaco")
    idp_falso.habilitar.assert_called_once_with(handle="3b9a-uuid-opaco")


def timedelta_una_hora():
    from datetime import timedelta

    return timedelta(hours=1)

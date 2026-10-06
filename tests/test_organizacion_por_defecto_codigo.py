"""El invariante de la organización por defecto: si un usuario tiene alguna
membresía ACTIVE, su `default_organization_id` es una de ellas.

Antes de este cambio, pausar (`PATCH .../status`) o quitar (`DELETE`) la
membresía por defecto dejaba la columna apuntando a una fila no activa. Como
`_load_current_user` valida contra ella toda petición sin `X-Organization-Id`,
la persona recibía 403 en todo —`/auth/organizations` incluido— aunque tuviera
otras membresías activas. Los clientes no mandan la cabecera sin una
organización elegida, así que el arreglo tiene que estar aquí y no en ellos.

Los tests entran por los endpoints, como producción: lo que importa no es que
la columna cambie sino que la persona vuelva a poder usar la app sin cabecera.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_identity_provider
from app.main import app as fastapi_app
from app.models.account_event import AccountEvent, EventType
from app.models.organization import Organization
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.user import User
from app.services.identity import IdentityProvider
from app.services.organization import OrganizationService
from app.utils.datetime import utcnow


@pytest.fixture
def idp_falso():
    doble = MagicMock(spec=IdentityProvider)
    fastapi_app.dependency_overrides[get_identity_provider] = lambda: doble
    yield doble
    fastapi_app.dependency_overrides.pop(get_identity_provider, None)


def _como(usuario):
    """Entra con la identidad de `usuario`, por donde entra producción."""
    return patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": usuario.cognito_sub}
    )


_AUTH = {"Authorization": "Bearer lo-que-sea"}


def _organizacion(db_session, cuenta_id, nombre):
    org = Organization(id=uuid4(), account_id=cuenta_id, name=nombre, status="ACTIVE")
    db_session.add(org)
    db_session.commit()
    return org


def _usuario(db_session, por_defecto, correo):
    user = User(
        id=uuid4(),
        default_organization_id=por_defecto.id,
        cognito_sub=f"sub-{correo}",
        external_id=correo,
        email=correo,
        full_name="Quien Sea",
        is_master=False,
        email_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _membresia(db_session, org, user, estado="ACTIVE", hace=None):
    fila = OrganizationUser(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.MEMBER.value,
        status=estado,
    )
    if hace is not None:
        fila.created_at = utcnow() - hace
    db_session.add(fila)
    db_session.commit()
    return fila


def _pausar(client, actor, org, victima, estado="INACTIVE"):
    with _como(actor):
        return client.patch(
            f"/api/v1/organizations/{org.id}/users/{victima.id}/status",
            json={"status": estado},
            headers=_AUTH,
        )


def _por_defecto_de(db_session, user):
    db_session.expire_all()
    return db_session.get(User, user.id).default_organization_id


@pytest.fixture
def con_dos(db_session, test_organization_data, test_account_data):
    """Una persona con su por defecto en la organización de prueba (donde
    `test_user_data` es owner) y una segunda membresía activa."""
    segunda = _organizacion(db_session, test_account_data.id, "Flota Norte")
    victima = _usuario(db_session, test_organization_data, "dos@example.com")
    _membresia(db_session, test_organization_data, victima)
    _membresia(db_session, segunda, victima)
    return victima, segunda


# ── Pausar ──────────────────────────────────────────────────────────────


def test_pausar_la_por_defecto_la_mueve_a_la_otra_activa(
    client, db_session, test_organization_data, test_user_data, con_dos
):
    victima, segunda = con_dos

    respuesta = _pausar(client, test_user_data, test_organization_data, victima)

    assert respuesta.status_code == status.HTTP_200_OK
    assert _por_defecto_de(db_session, victima) == segunda.id


def test_tras_pausar_la_por_defecto_sigue_entrando_sin_cabecera(
    client, db_session, test_organization_data, test_user_data, con_dos
):
    """El síntoma que motivó el cambio: sin cabecera, todo daba 403."""
    victima, segunda = con_dos
    _pausar(client, test_user_data, test_organization_data, victima)

    with _como(victima):
        me = client.get("/api/v1/auth/me", headers=_AUTH)
        lista = client.get("/api/v1/auth/organizations", headers=_AUTH)

    assert me.status_code == status.HTTP_200_OK
    assert me.json()["organization_id"] == str(segunda.id)
    assert lista.status_code == status.HTTP_200_OK
    assert [(f["organization_id"], f["is_default"]) for f in lista.json()] == [
        (str(segunda.id), True)
    ]


def test_pausar_otra_que_no_es_la_por_defecto_no_la_mueve(
    client, db_session, test_organization_data, test_user_data, test_account_data
):
    segunda = _organizacion(db_session, test_account_data.id, "Flota Sur")
    victima = _usuario(db_session, segunda, "no-default@example.com")
    _membresia(db_session, segunda, victima)
    _membresia(db_session, test_organization_data, victima)

    _pausar(client, test_user_data, test_organization_data, victima)

    assert _por_defecto_de(db_session, victima) == segunda.id


def test_pausar_la_unica_activa_deja_la_columna_como_esta(
    client, db_session, test_organization_data, test_user_data
):
    """La columna es NOT NULL y no hay otra a la cual moverla: el 403 que
    sigue es correcto, porque ya no tiene acceso a nada."""
    victima = _usuario(db_session, test_organization_data, "sola@example.com")
    _membresia(db_session, test_organization_data, victima)

    respuesta = _pausar(client, test_user_data, test_organization_data, victima)

    assert respuesta.status_code == status.HTTP_200_OK
    assert _por_defecto_de(db_session, victima) == test_organization_data.id


def test_elige_la_activa_mas_antigua(
    client, db_session, test_organization_data, test_user_data, test_account_data
):
    reciente = _organizacion(db_session, test_account_data.id, "Reciente")
    antigua = _organizacion(db_session, test_account_data.id, "Antigua")
    victima = _usuario(db_session, test_organization_data, "antigua@example.com")
    _membresia(db_session, test_organization_data, victima)
    _membresia(db_session, reciente, victima, hace=timedelta(days=1))
    _membresia(db_session, antigua, victima, hace=timedelta(days=30))

    _pausar(client, test_user_data, test_organization_data, victima)

    assert _por_defecto_de(db_session, victima) == antigua.id


def test_no_elige_una_membresia_pausada(
    client, db_session, test_organization_data, test_user_data, test_account_data
):
    pausada = _organizacion(db_session, test_account_data.id, "Pausada")
    activa = _organizacion(db_session, test_account_data.id, "Activa")
    victima = _usuario(db_session, test_organization_data, "pausada@example.com")
    _membresia(db_session, test_organization_data, victima)
    _membresia(db_session, pausada, victima, estado="INACTIVE", hace=timedelta(days=30))
    _membresia(db_session, activa, victima, hace=timedelta(days=1))

    _pausar(client, test_user_data, test_organization_data, victima)

    assert _por_defecto_de(db_session, victima) == activa.id


def test_la_pausa_audita_el_cambio_de_por_defecto(
    client, db_session, test_organization_data, test_user_data, con_dos
):
    victima, segunda = con_dos

    _pausar(client, test_user_data, test_organization_data, victima)

    evento = (
        db_session.query(AccountEvent)
        .filter(
            AccountEvent.event_type == EventType.ORG_USER_STATUS_CHANGED.value,
            AccountEvent.target_id == victima.id,
        )
        .one()
    )
    assert evento.event_metadata["default_organization_reassigned_to"] == str(
        segunda.id
    )


def test_la_pausa_sin_cambio_de_por_defecto_no_lo_menciona(
    client, db_session, test_organization_data, test_user_data
):
    victima = _usuario(db_session, test_organization_data, "sin-cambio@example.com")
    _membresia(db_session, test_organization_data, victima)

    _pausar(client, test_user_data, test_organization_data, victima)

    evento = (
        db_session.query(AccountEvent)
        .filter(
            AccountEvent.event_type == EventType.ORG_USER_STATUS_CHANGED.value,
            AccountEvent.target_id == victima.id,
        )
        .one()
    )
    assert "default_organization_reassigned_to" not in evento.event_metadata


# ── Reactivar y sumar: el invariante también al revés ───────────────────


def test_reactivar_a_quien_no_le_quedaba_ninguna_la_vuelve_por_defecto(
    client, db_session, test_organization_data, test_user_data, test_account_data
):
    """Por defecto en una organización donde está pausada y sin ninguna otra
    activa; al reactivarle otra, ésa pasa a ser la por defecto."""
    vieja = _organizacion(db_session, test_account_data.id, "Vieja")
    victima = _usuario(db_session, vieja, "vuelve@example.com")
    _membresia(db_session, vieja, victima, estado="INACTIVE")
    _membresia(db_session, test_organization_data, victima, estado="INACTIVE")

    respuesta = _pausar(
        client, test_user_data, test_organization_data, victima, estado="ACTIVE"
    )

    assert respuesta.status_code == status.HTTP_200_OK
    assert _por_defecto_de(db_session, victima) == test_organization_data.id


def test_reactivar_no_mueve_una_por_defecto_que_ya_es_valida(
    client, db_session, test_organization_data, test_user_data, test_account_data
):
    propia = _organizacion(db_session, test_account_data.id, "Propia")
    victima = _usuario(db_session, propia, "valida@example.com")
    _membresia(db_session, propia, victima)
    _membresia(db_session, test_organization_data, victima, estado="INACTIVE")

    _pausar(client, test_user_data, test_organization_data, victima, estado="ACTIVE")

    assert _por_defecto_de(db_session, victima) == propia.id


def test_sumar_a_quien_no_le_quedaba_ninguna_la_vuelve_por_defecto(
    client, db_session, test_organization_data, test_user_data, test_account_data
):
    vieja = _organizacion(db_session, test_account_data.id, "Vieja")
    victima = _usuario(db_session, vieja, "sumado@example.com")
    _membresia(db_session, vieja, victima, estado="INACTIVE")

    with _como(test_user_data):
        respuesta = client.post(
            f"/api/v1/organizations/{test_organization_data.id}/users",
            json={"user_id": str(victima.id), "role": "member"},
            headers=_AUTH,
        )

    assert respuesta.status_code == status.HTTP_201_CREATED
    assert _por_defecto_de(db_session, victima) == test_organization_data.id


# ── Quitar ──────────────────────────────────────────────────────────────


def test_quitar_la_por_defecto_la_mueve_y_lo_audita(
    client, db_session, test_organization_data, test_user_data, con_dos, idp_falso
):
    victima, segunda = con_dos

    with _como(test_user_data):
        respuesta = client.delete(
            f"/api/v1/organizations/{test_organization_data.id}/users/{victima.id}",
            headers=_AUTH,
        )

    assert respuesta.status_code == status.HTTP_204_NO_CONTENT
    assert _por_defecto_de(db_session, victima) == segunda.id
    evento = (
        db_session.query(AccountEvent)
        .filter(
            AccountEvent.event_type == EventType.ORG_USER_REMOVED.value,
            AccountEvent.target_id == victima.id,
        )
        .one()
    )
    assert evento.event_metadata["default_organization_reassigned_to"] == str(
        segunda.id
    )
    idp_falso.deshabilitar.assert_not_called()


def test_remove_member_del_servicio_tambien_la_mueve(
    db_session, test_organization_data, test_user_data, con_dos
):
    """Nadie llama hoy a `OrganizationService.remove_member`, pero borra
    membresías: si algún día se usa, no puede saltarse el invariante."""
    victima, segunda = con_dos

    OrganizationService.remove_member(
        db_session, test_organization_data.id, victima.id, test_user_data.id
    )

    assert _por_defecto_de(db_session, victima) == segunda.id


# ── La red: el listado no depende de la por defecto ─────────────────────


def test_el_listado_responde_aunque_la_por_defecto_este_rota(
    client, db_session, test_organization_data, test_account_data
):
    """Por si algún camino futuro se salta el invariante: el listado es la
    salida, así que no puede exigir la membresía por defecto."""
    rota = _organizacion(db_session, test_account_data.id, "Rota")
    victima = _usuario(db_session, rota, "rota@example.com")
    _membresia(db_session, rota, victima, estado="INACTIVE")
    _membresia(db_session, test_organization_data, victima)

    with _como(victima):
        lista = client.get("/api/v1/auth/organizations", headers=_AUTH)
        me = client.get("/api/v1/auth/me", headers=_AUTH)

    assert lista.status_code == status.HTTP_200_OK
    assert [(f["organization_id"], f["is_default"]) for f in lista.json()] == [
        (str(test_organization_data.id), False)
    ]
    # El resto del API sigue fallando cerrado contra la por defecto rota.
    assert me.status_code == status.HTTP_403_FORBIDDEN


def test_el_listado_ignora_la_cabecera(
    client, db_session, test_organization_data, test_account_data
):
    """Una cabecera hacia una organización revocada no puede tumbar el
    listado: es lo que el cliente pide justo para salir de ahí."""
    revocada = _organizacion(db_session, test_account_data.id, "Revocada")
    victima = _usuario(db_session, test_organization_data, "cabecera@example.com")
    _membresia(db_session, test_organization_data, victima)
    _membresia(db_session, revocada, victima, estado="INACTIVE")

    with _como(victima):
        lista = client.get(
            "/api/v1/auth/organizations",
            headers={**_AUTH, "X-Organization-Id": str(revocada.id)},
        )

    assert lista.status_code == status.HTTP_200_OK
    assert [f["organization_id"] for f in lista.json()] == [
        str(test_organization_data.id)
    ]


def test_el_listado_sigue_exigiendo_token(client):
    respuesta = client.get("/api/v1/auth/organizations")
    assert respuesta.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )

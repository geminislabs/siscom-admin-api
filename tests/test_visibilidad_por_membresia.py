"""Quién ve y gestiona una organización sale de la membresía, no de `is_master`.

`is_master` es del usuario: lo recibe quien se registra, para siempre y sin
organización. Con el selector de cuenta (`X-Organization-Id`), un maestro que
actuaba en otra organización donde solo es `member` veía todas sus unidades y
podía gestionarla (crear unidades, invitar, conceder permisos). La regla ahora
es la misma que aplica alert-distributor a push y WebSocket (ADR-008 §6):
`owner` con membresía activa en la organización en la que actúa la sesión.

Para quien actúa en su organización por defecto no cambia nada: `owner` ≡
maestro, verificado en producción el 19/10/2026.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import status

from app.models.organization import Organization
from app.models.organization_user import OrganizationUser
from app.models.unit import Unit
from app.models.user import User
from app.models.user_unit import UserUnit
from app.services.access_control import subject_for_user


@pytest.fixture
def maestro_con_dos_organizaciones(db_session, test_organization_data):
    """Owner y maestro de su organización, y `member` de otra con dos unidades,
    de las que solo tiene concedida una."""
    maestro = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        cognito_sub=f"sub-{uuid4()}",
        email="maestro@example.com",
        full_name="Maestro",
        is_master=True,
    )
    db_session.add(maestro)
    otra = Organization(
        id=uuid4(),
        name="Otra",
        status="ACTIVE",
        account_id=test_organization_data.account_id,
    )
    db_session.add(otra)
    db_session.flush()
    db_session.add_all(
        [
            OrganizationUser(
                organization_id=test_organization_data.id,
                user_id=maestro.id,
                role="owner",
            ),
            OrganizationUser(
                organization_id=otra.id, user_id=maestro.id, role="member"
            ),
        ]
    )
    concedida = Unit(id=uuid4(), organization_id=otra.id, name="Concedida")
    ajena = Unit(id=uuid4(), organization_id=otra.id, name="Ajena")
    db_session.add_all([concedida, ajena])
    db_session.flush()
    db_session.add(UserUnit(user_id=maestro.id, unit_id=concedida.id))
    db_session.commit()
    db_session.refresh(maestro)
    return {
        "maestro": maestro,
        "propia": test_organization_data,
        "otra": otra,
        "concedida": concedida,
        "ajena": ajena,
    }


def _como(client, user, organizacion, metodo, ruta, **kwargs):
    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": user.cognito_sub}
    ):
        return getattr(client, metodo)(
            ruta,
            headers={
                "Authorization": "Bearer lo-que-sea",
                "X-Organization-Id": str(organizacion.id),
            },
            **kwargs,
        )


def test_en_su_organizacion_el_owner_ve_todo(maestro_con_dos_organizaciones):
    e = maestro_con_dos_organizaciones
    assert e["maestro"].is_owner_of(e["propia"].id)
    assert subject_for_user(e["maestro"]).is_organization_wide


def test_en_otra_organizacion_es_un_miembro_aunque_sea_maestro(
    maestro_con_dos_organizaciones,
):
    e = maestro_con_dos_organizaciones
    maestro = e["maestro"]
    maestro._active_organization_id = e["otra"].id

    assert maestro.is_master is True
    assert not maestro.is_active_organization_owner
    sujeto = subject_for_user(maestro)
    assert not sujeto.is_organization_wide
    assert sujeto.user_id == maestro.id


def test_listar_unidades_en_otra_organizacion_solo_trae_lo_concedido(
    client, maestro_con_dos_organizaciones
):
    e = maestro_con_dos_organizaciones

    respuesta = _como(client, e["maestro"], e["otra"], "get", "/api/v1/units")

    assert respuesta.status_code == status.HTTP_200_OK, respuesta.text
    ids = {u["id"] for u in respuesta.json()}
    assert ids == {str(e["concedida"].id)}


def test_ver_una_unidad_no_concedida_en_otra_organizacion_falla(
    client, maestro_con_dos_organizaciones
):
    e = maestro_con_dos_organizaciones

    respuesta = _como(
        client, e["maestro"], e["otra"], "get", f"/api/v1/units/{e['ajena'].id}"
    )

    assert respuesta.status_code in (
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    )


def test_crear_unidades_en_otra_organizacion_esta_prohibido(
    client, maestro_con_dos_organizaciones
):
    e = maestro_con_dos_organizaciones

    respuesta = _como(
        client, e["maestro"], e["otra"], "post", "/api/v1/units", json={"name": "X"}
    )

    assert respuesta.status_code == status.HTTP_403_FORBIDDEN


def test_una_membresia_owner_pausada_no_cuenta(
    db_session, maestro_con_dos_organizaciones
):
    e = maestro_con_dos_organizaciones
    membresia = (
        db_session.query(OrganizationUser)
        .filter(
            OrganizationUser.user_id == e["maestro"].id,
            OrganizationUser.organization_id == e["propia"].id,
        )
        .one()
    )
    membresia.status = "INACTIVE"
    db_session.commit()
    db_session.refresh(e["maestro"])

    assert not e["maestro"].is_owner_of(e["propia"].id)


# ---------------------------------------------------------------------------
# Pertenencia: la membresía, no la organización por defecto
# ---------------------------------------------------------------------------


@pytest.fixture
def miembro_que_viene_de_otra(db_session, test_organization_data):
    """Nació en otra organización y es `member` activo de la del owner."""
    origen = Organization(
        id=uuid4(),
        name="Origen",
        status="ACTIVE",
        account_id=test_organization_data.account_id,
    )
    db_session.add(origen)
    db_session.flush()
    miembro = User(
        id=uuid4(),
        default_organization_id=origen.id,
        cognito_sub=f"sub-{uuid4()}",
        email="viene-de-otra@example.com",
        full_name="Viene de otra",
        is_master=False,
    )
    db_session.add(miembro)
    db_session.flush()
    db_session.add_all(
        [
            OrganizationUser(
                organization_id=origen.id, user_id=miembro.id, role="owner"
            ),
            OrganizationUser(
                organization_id=test_organization_data.id,
                user_id=miembro.id,
                role="member",
            ),
        ]
    )
    db_session.commit()
    return miembro


def test_la_lista_de_usuarios_incluye_a_quien_viene_de_otra(
    client, test_user_data, test_organization_data, miembro_que_viene_de_otra
):
    respuesta = _como(
        client, test_user_data, test_organization_data, "get", "/api/v1/users"
    )

    assert respuesta.status_code == status.HTTP_200_OK, respuesta.text
    assert str(miembro_que_viene_de_otra.id) in {u["id"] for u in respuesta.json()}


def test_se_le_puede_conceder_una_unidad_a_quien_viene_de_otra(
    client,
    test_user_data,
    test_organization_data,
    test_unit_data,
    miembro_que_viene_de_otra,
):
    """Antes respondía 404: el destino se buscaba por su organización por
    defecto. Con la regla por membresía, eso lo dejaba sin ver nada aquí y sin
    forma de arreglarlo desde Nexus."""
    respuesta = _como(
        client,
        test_user_data,
        test_organization_data,
        "post",
        "/api/v1/user-units",
        json={
            "user_id": str(miembro_que_viene_de_otra.id),
            "unit_id": str(test_unit_data.id),
        },
    )

    assert respuesta.status_code == status.HTTP_201_CREATED, respuesta.text


def test_no_se_le_concede_una_unidad_a_quien_ya_no_es_miembro(
    client,
    db_session,
    test_user_data,
    test_organization_data,
    test_unit_data,
    miembro_que_viene_de_otra,
):
    membresia = (
        db_session.query(OrganizationUser)
        .filter(
            OrganizationUser.user_id == miembro_que_viene_de_otra.id,
            OrganizationUser.organization_id == test_organization_data.id,
        )
        .one()
    )
    membresia.status = "INACTIVE"
    db_session.commit()

    respuesta = _como(
        client,
        test_user_data,
        test_organization_data,
        "post",
        "/api/v1/user-units",
        json={
            "user_id": str(miembro_que_viene_de_otra.id),
            "unit_id": str(test_unit_data.id),
        },
    )

    assert respuesta.status_code == status.HTTP_404_NOT_FOUND

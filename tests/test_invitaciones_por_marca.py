"""Las invitaciones viven en la marca de quien invita (§26, migración 042).

Invitar, reenviar y aceptar eran las tres consultas por correo que quedaban sin
acotar por marca: buscaban `User.email` en todas. Y aceptar creaba al usuario
en la marca por defecto aunque el correo de invitación hubiera salido con la de
quien invitó. Aquí cada caso usa el mismo correo en dos marcas, que es
exactamente lo que el white-label tiene que permitir.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_identity_provider
from app.main import app as fastapi_app
from app.models.account import Account
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.token_confirmacion import TokenConfirmacion, TokenType
from app.models.user import User, UserStatus
from app.services.identity import IdentityProvider
from app.utils.datetime import utcnow

CORREO = "repetido@example.com"


@pytest.fixture
def idp_falso():
    doble = MagicMock(spec=IdentityProvider)
    doble.sujeto_de.return_value = None
    doble.crear_credencial.return_value = "sub-nuevo"
    fastapi_app.dependency_overrides[get_identity_provider] = lambda: doble
    yield doble
    fastapi_app.dependency_overrides.pop(get_identity_provider, None)


@pytest.fixture
def marca(db_session):
    cid = uuid4()
    cuenta = Account(id=cid, name="Mero Mero", status="ACTIVE", account_path=[cid])
    db_session.add(cuenta)
    db_session.commit()
    return cuenta


def _usuario(db_session, organizacion, correo, marca_id=None, estado="ACTIVE"):
    user = User(
        id=uuid4(),
        default_organization_id=organizacion.id,
        cognito_sub=f"sub-{uuid4().hex[:8]}",
        external_id=str(uuid4()),
        email=correo,
        full_name="Alguien",
        is_master=False,
        brand_account_id=marca_id,
        status=estado,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _invitacion(db_session, organizacion, token, marca_id=None):
    db_session.add(
        TokenConfirmacion(
            id=uuid4(),
            token=token,
            organization_id=organizacion.id,
            email=CORREO,
            full_name="Persona Invitada",
            expires_at=utcnow() + timedelta(hours=1),
            used=False,
            type=TokenType.INVITATION,
            brand_account_id=marca_id,
        )
    )
    db_session.commit()


# ── Invitar ─────────────────────────────────────────────────────────────


def test_el_mismo_correo_activo_en_otra_marca_no_bloquea_la_invitacion(
    authenticated_client, db_session, test_organization_data, test_user_data, marca
):
    _usuario(db_session, test_organization_data, CORREO)  # marca por defecto
    test_user_data.brand_account_id = marca.id  # quien invita es de Mero Mero
    db_session.commit()

    r = authenticated_client.post(
        "/api/v1/users/invite", json={"email": CORREO, "full_name": "Otra Persona"}
    )

    assert r.status_code == status.HTTP_201_CREATED
    token = db_session.query(TokenConfirmacion).filter_by(email=CORREO).one()
    assert token.brand_account_id == marca.id


def test_en_la_misma_marca_un_activo_sigue_bloqueando(
    authenticated_client, db_session, test_organization_data, test_user_data, marca
):
    _usuario(db_session, test_organization_data, CORREO, marca_id=marca.id)
    test_user_data.brand_account_id = marca.id
    db_session.commit()

    r = authenticated_client.post(
        "/api/v1/users/invite", json={"email": CORREO, "full_name": "La Misma"}
    )

    assert r.status_code == status.HTTP_400_BAD_REQUEST


def test_una_invitacion_pendiente_en_otra_marca_no_bloquea(
    authenticated_client, db_session, test_organization_data, test_user_data, marca
):
    _invitacion(db_session, test_organization_data, "tok-de-geminis")
    test_user_data.brand_account_id = marca.id
    db_session.commit()

    r = authenticated_client.post(
        "/api/v1/users/invite", json={"email": CORREO, "full_name": "Otra Persona"}
    )

    assert r.status_code == status.HTTP_201_CREATED


def test_la_marca_por_defecto_sigue_como_siempre(
    authenticated_client, db_session, test_organization_data
):
    """Producción hoy: todo NULL. La invitación nace sin marca."""
    r = authenticated_client.post(
        "/api/v1/users/invite", json={"email": CORREO, "full_name": "De Geminis"}
    )

    assert r.status_code == status.HTTP_201_CREATED
    token = db_session.query(TokenConfirmacion).filter_by(email=CORREO).one()
    assert token.brand_account_id is None


# ── Aceptar ─────────────────────────────────────────────────────────────


def test_aceptar_crea_al_usuario_en_la_marca_de_la_invitacion(
    client, db_session, test_organization_data, marca, idp_falso
):
    _invitacion(db_session, test_organization_data, "tok-mero", marca_id=marca.id)

    with patch(
        "app.api.v1.endpoints.users.proveedor_para_cuenta", return_value=idp_falso
    ) as proveedor:
        r = client.post(
            "/api/v1/users/accept-invitation",
            json={"token": "tok-mero", "password": "La-nueva-1!"},
        )

    assert r.status_code == status.HTTP_201_CREATED
    nuevo = db_session.query(User).filter_by(email=CORREO).one()
    assert nuevo.brand_account_id == marca.id
    # La credencial va al proveedor de esa marca, no al inyectado por defecto.
    assert proveedor.call_args.args[0].id == marca.id


def test_aceptar_no_reactiva_a_alguien_de_otra_marca(
    client, db_session, test_organization_data, marca, idp_falso
):
    """El INACTIVE de Geminis con el mismo correo es otra persona: aceptar una
    invitación de Mero Mero crea una fila nueva y no le toca la suya."""
    ajeno = _usuario(
        db_session, test_organization_data, CORREO, estado=UserStatus.INACTIVE.value
    )
    _invitacion(db_session, test_organization_data, "tok-mero", marca_id=marca.id)

    with patch(
        "app.api.v1.endpoints.users.proveedor_para_cuenta", return_value=idp_falso
    ):
        r = client.post(
            "/api/v1/users/accept-invitation",
            json={"token": "tok-mero", "password": "La-nueva-1!"},
        )

    assert r.status_code == status.HTTP_201_CREATED
    db_session.refresh(ajeno)
    assert ajeno.status == UserStatus.INACTIVE.value
    filas = db_session.query(User).filter_by(email=CORREO).all()
    assert {f.brand_account_id for f in filas} == {None, marca.id}


def test_una_invitacion_anterior_a_la_042_sigue_en_la_marca_por_defecto(
    client, db_session, test_organization_data, idp_falso
):
    _invitacion(db_session, test_organization_data, "tok-viejo")  # NULL

    with patch("app.api.v1.endpoints.users.proveedor_para_cuenta") as proveedor:
        r = client.post(
            "/api/v1/users/accept-invitation",
            json={"token": "tok-viejo", "password": "La-nueva-1!"},
        )

    assert r.status_code == status.HTTP_201_CREATED
    assert db_session.query(User).filter_by(email=CORREO).one().brand_account_id is None
    proveedor.assert_not_called()  # gobierna el idp inyectado, como hoy
    membresia = db_session.query(OrganizationUser).one_or_none()
    assert membresia is None or membresia.role == OrganizationRole.MEMBER.value


# ── Reenviar ────────────────────────────────────────────────────────────


def test_reenviar_conserva_la_marca_y_no_mira_otras(
    authenticated_client, db_session, test_organization_data, test_user_data, marca
):
    _usuario(db_session, test_organization_data, CORREO)  # activo en Geminis
    _invitacion(db_session, test_organization_data, "tok-mero", marca_id=marca.id)
    test_user_data.brand_account_id = marca.id
    db_session.commit()

    r = authenticated_client.post(
        "/api/v1/users/resend-invitation", json={"email": CORREO}
    )

    assert r.status_code == status.HTTP_200_OK
    vigente = (
        db_session.query(TokenConfirmacion).filter_by(email=CORREO, used=False).one()
    )
    assert vigente.token != "tok-mero"
    assert vigente.brand_account_id == marca.id

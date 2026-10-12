"""`require_account_permission` y la sesión (`GET /auth/me`) con permisos.

Rebanada 1 de B4 (D6): los endpoints preguntan por permiso, no por rol. Aquí
se prueba el guard que lo hace y lo que la sesión expone para que el menú de
los clientes se derive de lo mismo.

POR QUÉ CADA 403 SE PRUEBA CON UN TOKEN VÁLIDO
==============================================
La lección del plano de control (v1.36.0/v1.38.0): un test que solo prueba la
ausencia de credencial no prueba la autorización, porque esa petición la
rechaza la autenticación antes de llegar a ella. Cada caso de 403 de este
fichero entra con la identidad de alguien real —un billing, un member, el owner
de otra cuenta, el owner de la organización sin rol en la cuenta— y lo único
que cambia es lo que el guard tiene que decidir.

El catálogo de la base de tests lo siembra el fixture, no la migración: esta
base sale de `create_all()`. Que la migración siembre lo que debe lo prueba
`tests/test_permisos_esquema.py`.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient

from app.api.deps import AuthResult, require_account_permission
from app.db.session import get_db
from app.models.account import Account
from app.models.account_user import AccountUser
from app.models.capability import AccountCapability, Capability
from app.models.organization import Organization
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.permission import Permission, Role, RolePermission
from app.models.user import User

PERMISO = "pruebas.escribir"

_AUTH = {"Authorization": "Bearer lo-que-sea"}


def _como(usuario):
    """Entra con la identidad de `usuario`, por donde entra producción."""
    return patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": usuario.cognito_sub}
    )


@pytest.fixture
def catalogo(db_session):
    """Los cuatro roles de sistema de cuenta y un permiso para owner y admin."""
    roles = {}
    for code in ("owner", "admin", "billing", "member"):
        rol = Role(scope="account", code=code, name=code, is_system=True)
        db_session.add(rol)
        roles[code] = rol
    db_session.add(
        Permission(code=PERMISO, description="Permiso de prueba", scope="account")
    )
    db_session.flush()
    for code in ("owner", "admin"):
        db_session.add(
            RolePermission(
                role_id=roles[code].id, permission_code=PERMISO, scope="account"
            )
        )
    db_session.commit()
    return roles


def _cuenta(db_session, nombre):
    cid = uuid.uuid4()
    cuenta = Account(id=cid, name=nombre, status="ACTIVE", account_path=[cid])
    db_session.add(cuenta)
    db_session.flush()
    org = Organization(
        id=uuid.uuid4(), account_id=cid, name=f"{nombre} org", status="ACTIVE"
    )
    db_session.add(org)
    db_session.commit()
    return cuenta, org


def _persona(db_session, org, correo, *, rol_de_cuenta=None):
    """Alguien con membresía de organización y, si se pide, rol en la cuenta."""
    user = User(
        id=uuid.uuid4(),
        default_organization_id=org.id,
        cognito_sub=f"sub-{correo}",
        external_id=correo,
        email=correo,
        full_name="Quien Sea",
        is_master=False,
        email_verified=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        OrganizationUser(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.OWNER.value,
        )
    )
    if rol_de_cuenta is not None:
        db_session.add(
            AccountUser(
                account_id=org.account_id,
                user_id=user.id,
                role=rol_de_cuenta,
            )
        )
    db_session.commit()
    return user


@pytest.fixture
def guardado(db_session):
    """Una app mínima con una ruta protegida por el guard, como la usará B4."""
    app = FastAPI()

    @app.put("/accounts/{account_id}/algo")
    def ruta(
        account_id: uuid.UUID,
        auth: AuthResult = Depends(require_account_permission(PERMISO)),
    ):
        return {
            "account_id": str(auth.account_id),
            "account_role": auth.account_role,
            "user_id": str(auth.user_id),
        }

    @app.put("/accounts/{account_id}/fuera-del-catalogo")
    def otra(
        account_id: uuid.UUID,
        auth: AuthResult = Depends(require_account_permission("pruebas.inexistente")),
    ):
        return {"ok": True}

    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


# ── El guard ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("rol", ["owner", "admin"])
def test_owner_y_admin_de_la_cuenta_pasan(db_session, catalogo, guardado, rol):
    cuenta, org = _cuenta(db_session, "Mero Mero")
    persona = _persona(db_session, org, f"{rol}@example.com", rol_de_cuenta=rol)

    with _como(persona):
        r = guardado.put(f"/accounts/{cuenta.id}/algo", headers=_AUTH)

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {
        "account_id": str(cuenta.id),
        "account_role": rol,
        "user_id": str(persona.id),
    }


@pytest.mark.parametrize("rol", ["billing", "member"])
def test_un_rol_sin_el_permiso_recibe_403(db_session, catalogo, guardado, rol):
    cuenta, org = _cuenta(db_session, "Mero Mero")
    persona = _persona(db_session, org, f"{rol}@example.com", rol_de_cuenta=rol)

    with _como(persona):
        r = guardado.put(f"/accounts/{cuenta.id}/algo", headers=_AUTH)

    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_el_owner_de_otra_cuenta_recibe_403(db_session, catalogo, guardado):
    """El permiso vale en la cuenta de la membresía, no en cualquiera."""
    ajena, _ = _cuenta(db_session, "Ajena")
    _, org = _cuenta(db_session, "Propia")
    owner_de_otra = _persona(db_session, org, "otra@example.com", rol_de_cuenta="owner")

    with _como(owner_de_otra):
        r = guardado.put(f"/accounts/{ajena.id}/algo", headers=_AUTH)

    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_el_owner_de_la_organizacion_sin_rol_en_la_cuenta_recibe_403(
    db_session, catalogo, guardado
):
    """El rol de organización no cuenta para un permiso de alcance cuenta."""
    cuenta, org = _cuenta(db_session, "Mero Mero")
    solo_organizacion = _persona(db_session, org, "org@example.com")

    with _como(solo_organizacion):
        r = guardado.put(f"/accounts/{cuenta.id}/algo", headers=_AUTH)

    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_un_permiso_que_el_catalogo_no_tiene_da_403_tambien_al_owner(
    db_session, catalogo, guardado
):
    """Falla cerrado: sin la fila del catálogo nadie pasa, ni el owner."""
    cuenta, org = _cuenta(db_session, "Mero Mero")
    owner = _persona(db_session, org, "owner@example.com", rol_de_cuenta="owner")

    with _como(owner):
        r = guardado.put(f"/accounts/{cuenta.id}/fuera-del-catalogo", headers=_AUTH)

    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_sin_catalogo_sembrado_nadie_pasa(db_session, guardado):
    """Si la migración 038 no corrió, el resultado es 403, no acceso."""
    cuenta, org = _cuenta(db_session, "Mero Mero")
    owner = _persona(db_session, org, "owner@example.com", rol_de_cuenta="owner")

    with _como(owner):
        r = guardado.put(f"/accounts/{cuenta.id}/algo", headers=_AUTH)

    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_sin_credencial_es_401(db_session, catalogo, guardado):
    cuenta, _ = _cuenta(db_session, "Mero Mero")

    r = guardado.put(f"/accounts/{cuenta.id}/algo")

    assert r.status_code == status.HTTP_401_UNAUTHORIZED


# ── La sesión ───────────────────────────────────────────────────────────


def test_la_sesion_expone_rol_permisos_y_capabilities_de_la_cuenta(
    client, db_session, catalogo
):
    cuenta, org = _cuenta(db_session, "Mero Mero")
    owner = _persona(db_session, org, "owner@example.com", rol_de_cuenta="owner")
    marca = Capability(
        code="white_label_enabled", description="Marca propia", value_type="bool"
    )
    db_session.add(marca)
    db_session.flush()
    db_session.add(
        AccountCapability(account_id=cuenta.id, capability_id=marca.id, value_bool=True)
    )
    db_session.commit()

    with _como(owner):
        me = client.get("/api/v1/auth/me", headers=_AUTH)

    assert me.status_code == status.HTTP_200_OK
    cuerpo = me.json()
    assert cuerpo["account_role"] == "owner"
    assert cuerpo["account_permissions"] == [PERMISO]
    assert cuerpo["account_capabilities"]["white_label_enabled"] is True
    # Las que nadie concedió salen con su default restrictivo, no ausentes.
    assert cuerpo["account_capabilities"]["max_custom_domains"] == 0


def test_la_sesion_de_un_member_no_trae_permisos(client, db_session, catalogo):
    cuenta, org = _cuenta(db_session, "Mero Mero")
    member = _persona(db_session, org, "member@example.com", rol_de_cuenta="member")

    with _como(member):
        cuerpo = client.get("/api/v1/auth/me", headers=_AUTH).json()

    assert cuerpo["account_role"] == "member"
    assert cuerpo["account_permissions"] == []
    assert cuerpo["account_capabilities"]["white_label_enabled"] is False


def test_sin_rol_en_la_cuenta_la_sesion_dice_null(client, db_session, catalogo):
    """Invitado a una organización: owner ahí, nada en la cuenta."""
    _, org = _cuenta(db_session, "Mero Mero")
    invitado = _persona(db_session, org, "org@example.com")

    with _como(invitado):
        cuerpo = client.get("/api/v1/auth/me", headers=_AUTH).json()

    assert cuerpo["role"] == "owner"
    assert cuerpo["account_role"] is None
    assert cuerpo["account_permissions"] == []


def test_un_camino_de_cuenta_roto_no_tumba_la_sesion(client, db_session, catalogo):
    """`account_path` vacío: el resolvedor se niega y la sesión sale sin
    capabilities —«nada concedido»— en vez de un 500 para todos."""
    _, org = _cuenta(db_session, "Mero Mero")
    owner = _persona(db_session, org, "owner@example.com", rol_de_cuenta="owner")
    cuenta = db_session.get(Account, org.account_id)
    cuenta.account_path = []
    db_session.commit()

    with _como(owner):
        me = client.get("/api/v1/auth/me", headers=_AUTH)

    assert me.status_code == status.HTTP_200_OK
    assert me.json()["account_capabilities"] == {}
    assert me.json()["account_permissions"] == [PERMISO]

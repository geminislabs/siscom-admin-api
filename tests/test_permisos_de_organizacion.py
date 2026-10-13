"""`require_organization_permission` y el reparto de la migración 040.

Los quince endpoints que preguntaban por rol (`require_organization_role`)
ahora preguntan por permiso. La promesa del cambio es que **nadie gana ni
pierde acceso**; este fichero la comprueba en tres niveles:

1. El reparto: cada permiso de la 040 lo reciben exactamente los roles que la
   jerarquía vieja dejaba pasar en los endpoints que lo exigen. La jerarquía
   se copia aquí tal como estaba en `app/api/deps.py` hasta este cambio.
2. Los endpoints: cada uno pide el permiso que dice la tabla, leído del AST.
3. El guard, por HTTP y con la identidad de alguien real (la lección del plano
   de control: un 403 sin credencial no prueba la autorización), contra el
   catálogo que siembra `tests/conftest.py` con el SQL de la propia 040.
"""

import ast
import importlib.util
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient

from app.api.deps import AuthResult, require_organization_permission
from app.db.session import get_db
from app.models.account import Account
from app.models.organization import Organization
from app.models.organization_user import MembershipStatus, OrganizationUser
from app.models.user import User

RAIZ = Path(__file__).resolve().parents[1]
ENDPOINTS = RAIZ / "app/api/v1/endpoints"

_spec = importlib.util.spec_from_file_location(
    "migracion_040",
    RAIZ / "app/db/migrations/versions/040_permisos_de_organizacion.py",
)
migracion = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migracion)
REPARTO = {code: set(roles) for code, _, roles in migracion.PERMISOS}

# La jerarquía de `require_organization_role`, copiada sin cambios.
JERARQUIA_VIEJA = {
    "owner": ["owner", "admin", "billing", "member"],
    "admin": ["admin", "billing", "member"],
    "billing": ["billing", "member"],
    "member": ["member"],
}

# (fichero, función) -> (roles que pedía antes, permiso que pide ahora)
ANTES_Y_AHORA = {
    ("accounts.py", "update_account"): (("owner",), "accounts.write"),
    ("organization_capabilities.py", "list_organization_capabilities"): (
        ("member",),
        "capabilities.read",
    ),
    ("organization_capabilities.py", "create_or_update_capability_override"): (
        ("owner",),
        "capabilities.override",
    ),
    ("organization_capabilities.py", "delete_capability_override"): (
        ("owner",),
        "capabilities.override",
    ),
    ("organization_users.py", "list_organization_users"): (
        ("member",),
        "organization_users.read",
    ),
    ("organization_users.py", "add_user_to_organization"): (
        ("admin",),
        "organization_users.manage",
    ),
    ("organization_users.py", "update_user_role"): (
        ("admin",),
        "organization_users.manage",
    ),
    ("organization_users.py", "update_membership_status"): (
        ("admin",),
        "organization_users.manage",
    ),
    ("organization_users.py", "remove_user_from_organization"): (
        ("admin",),
        "organization_users.manage",
    ),
    ("organizations.py", "create_organization"): (("owner",), "organizations.write"),
    ("organizations.py", "list_organizations"): (("member",), "organizations.read"),
    ("organizations.py", "get_organization"): (("member",), "organizations.read"),
    ("organizations.py", "update_organization"): (("owner",), "organizations.write"),
    # `require_billing_access` era `require_organization_role("owner", "billing")`.
    ("subscriptions.py", "cancel_subscription"): (
        ("owner", "billing"),
        "subscriptions.manage",
    ),
    ("subscriptions.py", "toggle_auto_renew"): (
        ("owner", "billing"),
        "subscriptions.manage",
    ),
}


def _pasaban(pedidos) -> set[str]:
    """Los roles que la jerarquía vieja dejaba pasar ante `pedidos`."""
    return {
        rol
        for rol, incluye in JERARQUIA_VIEJA.items()
        if any(p in incluye for p in pedidos)
    }


def _permiso_que_pide(fichero: str, funcion: str) -> str:
    arbol = ast.parse((ENDPOINTS / fichero).read_text())
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.FunctionDef) and nodo.name == funcion:
            for llamada in ast.walk(nodo):
                if (
                    isinstance(llamada, ast.Call)
                    and getattr(llamada.func, "id", None)
                    == "require_organization_permission"
                ):
                    return llamada.args[0].value
            raise AssertionError(f"{fichero}:{funcion} no pide permiso")
    raise AssertionError(f"{fichero}:{funcion} no existe")


# ── 1 y 2. Nadie gana ni pierde acceso ─────────────────────────────────


@pytest.mark.parametrize("endpoint", sorted(ANTES_Y_AHORA))
def test_el_endpoint_deja_pasar_a_los_mismos_roles_que_antes(endpoint):
    pedidos, permiso = ANTES_Y_AHORA[endpoint]
    assert _permiso_que_pide(*endpoint) == permiso
    assert REPARTO[permiso] == _pasaban(pedidos)


def test_cada_permiso_de_la_040_lo_pide_algun_endpoint_de_la_tabla():
    assert set(REPARTO) == {permiso for _, permiso in ANTES_Y_AHORA.values()}


def test_ya_nadie_pregunta_por_rol():
    restos = [
        str(f.relative_to(RAIZ))
        for f in (RAIZ / "app").rglob("*.py")
        if "migrations" not in f.parts
        for nodo in ast.walk(ast.parse(f.read_text()))
        if isinstance(nodo, ast.Name)
        and nodo.id in ("require_organization_role", "require_billing_access")
    ]
    assert restos == []


# ── 3. El guard ─────────────────────────────────────────────────────────

_AUTH = {"Authorization": "Bearer lo-que-sea"}


def _como(usuario):
    return patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": usuario.cognito_sub}
    )


def _organizacion(db_session):
    cid = uuid.uuid4()
    db_session.add(
        Account(id=cid, name="Mero Mero", status="ACTIVE", account_path=[cid])
    )
    db_session.flush()
    org = Organization(id=uuid.uuid4(), account_id=cid, name="Org", status="ACTIVE")
    db_session.add(org)
    db_session.commit()
    return org


def _persona(db_session, org, rol=None, estado=MembershipStatus.ACTIVE.value):
    correo = f"{uuid.uuid4().hex[:8]}@example.com"
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
    if rol:
        db_session.add(
            OrganizationUser(
                organization_id=org.id, user_id=user.id, role=rol, status=estado
            )
        )
    db_session.commit()
    return user


@pytest.fixture
def cliente(db_session):
    """Una ruta por permiso de la 040, más una fuera del catálogo."""
    app = FastAPI()

    def _ruta(permiso):
        def ruta(auth: AuthResult = Depends(require_organization_permission(permiso))):
            return {
                "organization_id": str(auth.organization_id),
                "organization_role": auth.organization_role,
                "user_id": str(auth.user_id),
            }

        app.get(f"/p/{permiso}")(ruta)

    for permiso in [*REPARTO, "pruebas.inexistente"]:
        _ruta(permiso)

    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


@pytest.mark.parametrize("rol", ["owner", "admin", "billing", "member"])
def test_cada_rol_pasa_justo_donde_el_catalogo_dice(db_session, cliente, rol):
    org = _organizacion(db_session)
    persona = _persona(db_session, org, rol)

    with _como(persona):
        for permiso, roles in REPARTO.items():
            r = cliente.get(f"/p/{permiso}", headers=_AUTH)
            esperado = status.HTTP_200_OK if rol in roles else status.HTTP_403_FORBIDDEN
            assert r.status_code == esperado, (rol, permiso)
            if esperado == status.HTTP_200_OK:
                assert r.json() == {
                    "organization_id": str(org.id),
                    "organization_role": rol,
                    "user_id": str(persona.id),
                }


def test_sin_membresia_no_pasa_ni_lo_que_es_de_todos(db_session, cliente):
    persona = _persona(db_session, _organizacion(db_session))

    with _como(persona):
        r = cliente.get("/p/organizations.read", headers=_AUTH)

    assert r.status_code == status.HTTP_403_FORBIDDEN
    assert "organizations.read" in r.json()["detail"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Hueco previo a este cambio: OrganizationService.get_user_role no mira "
        "OrganizationUser.status, así que pausar la única membresía de alguien "
        "no le quita el rol. Este PR no cambia accesos; se corrige aparte, y "
        "entonces este xfail estricto falla y hay que quitarlo."
    ),
)
def test_una_membresia_inactiva_no_cuenta_aunque_sea_de_owner(db_session, cliente):
    org = _organizacion(db_session)
    persona = _persona(db_session, org, "owner", MembershipStatus.INACTIVE.value)

    with _como(persona):
        r = cliente.get("/p/organizations.read", headers=_AUTH)

    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_un_permiso_fuera_del_catalogo_da_403_tambien_al_owner(db_session, cliente):
    persona = _persona(db_session, _organizacion(db_session), "owner")

    with _como(persona):
        r = cliente.get("/p/pruebas.inexistente", headers=_AUTH)

    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_un_token_sin_sub_es_401_y_un_desconocido_404(db_session, cliente):
    with patch("app.api.deps.verify_cognito_token", return_value={}):
        assert cliente.get("/p/organizations.read", headers=_AUTH).status_code == 401
    with patch("app.api.deps.verify_cognito_token", return_value={"sub": "nadie"}):
        assert cliente.get("/p/organizations.read", headers=_AUTH).status_code == 404

"""`require_organization_permission` y el reparto de las migraciones 040 y 041.

Los quince endpoints que preguntaban por rol (`require_organization_role`)
ahora preguntan por permiso. La promesa de la 040 fue que **nadie ganaba ni
perdía acceso**; desde entonces, cada cambio de acceso es una migración que lo
declara (`RETIRADOS` de la 041). Este fichero lo comprueba en tres niveles:

1. El reparto: cada permiso lo reciben exactamente los roles que la jerarquía
   vieja dejaba pasar en los endpoints que lo exigen, **menos** lo que alguna
   migración posterior retiró a propósito. La jerarquía se copia aquí tal como
   estaba en `app/api/deps.py` hasta la 040.
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


def _migracion(nombre):
    spec = importlib.util.spec_from_file_location(
        f"migracion_{nombre}", RAIZ / f"app/db/migrations/versions/{nombre}.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# Lo que sembró la 040 y lo que la 041 retiró: el reparto vigente.
SEMBRADO = {
    code: set(roles)
    for code, _, roles in _migracion("040_permisos_de_organizacion").PERMISOS
}
RETIRADO = {
    code: set(roles)
    for code, roles in _migracion("041_overrides_sin_autoservicio").RETIRADOS
}
REPARTO = {code: roles - RETIRADO.get(code, set()) for code, roles in SEMBRADO.items()}

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
def test_la_040_dejo_pasar_a_los_mismos_roles_que_antes(endpoint):
    pedidos, permiso = ANTES_Y_AHORA[endpoint]
    assert _permiso_que_pide(*endpoint) == permiso
    assert SEMBRADO[permiso] == _pasaban(pedidos)


def test_lo_unico_que_cambio_despues_es_lo_que_la_041_declara():
    """Nadie gana acceso, y quien lo pierde está escrito en una migración."""
    for permiso, roles in REPARTO.items():
        assert roles <= SEMBRADO[permiso], permiso
    perdido = {
        p: SEMBRADO[p] - REPARTO[p] for p in SEMBRADO if SEMBRADO[p] - REPARTO[p]
    }
    assert perdido == {"capabilities.override": {"owner"}}


def test_nadie_puede_escribir_overrides_desde_nexus():
    """La 041: un override de capabilities es una decisión comercial, no autoservicio."""
    assert REPARTO["capabilities.override"] == set()


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


# ── La 041, contra la ruta real ─────────────────────────────────────────


def test_el_owner_no_puede_subirse_un_limite_con_un_override(db_session, client):
    """El hueco que cierra la 041, por donde entraba: la ruta de verdad, con la
    identidad del owner que acaba de registrarse."""
    from app.models.capability import Capability, OrganizationCapability

    org = _organizacion(db_session)
    owner = _persona(db_session, org, "owner")
    db_session.add(
        Capability(code="max_devices", description="Límite", value_type="int")
    )
    db_session.commit()

    with _como(owner):
        creado = client.post(
            f"/api/v1/organizations/{org.id}/capabilities",
            json={"capability_code": "max_devices", "value_int": 100000},
            headers=_AUTH,
        )
        listado = client.get(
            f"/api/v1/organizations/{org.id}/capabilities", headers=_AUTH
        )

    assert creado.status_code == status.HTTP_403_FORBIDDEN
    assert "capabilities.override" in creado.json()["detail"]
    assert db_session.query(OrganizationCapability).count() == 0
    # Leerlas sigue abierto para cualquier miembro.
    assert listado.status_code == status.HTTP_200_OK

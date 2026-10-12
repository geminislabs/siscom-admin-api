"""La migración 038 (catálogo de permisos, D6 de B4) hace lo que dice.

Sobre la base del comparador —snapshot productivo + `alembic upgrade head`—,
no sobre `create_all()`: las FK compuestas que atan el alcance del rol al del
permiso solo las crea la migración, y la siembra de los roles de sistema
también. Ver `tests/esquema_desechable.py`.

Además fija la regla del catálogo: un permiso entra en la misma migración que
el endpoint que lo exige. `test_cada_permiso_del_catalogo_lo_exige_un_endpoint`
y su inverso fallan si una de las dos mitades llega sin la otra.
"""

import ast
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests import esquema_desechable as desechable

BASE = "siscom_test_permisos"
REVISION_ANTERIOR = "037_por_defecto_activa"

RAIZ_APP = Path(__file__).resolve().parents[1] / "app"

# require_account_permission("branding.write") -> ("account", "branding.write")
_GUARDS = {
    "require_account_permission": "account",
    "require_organization_permission": "organization",
}


@pytest.fixture(scope="module")
def engine():
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    """Conexión en una transacción que siempre se revierte."""
    with engine.connect() as c:
        tx = c.begin()
        try:
            yield c
        finally:
            tx.rollback()


def _rol(conn, scope: str, code: str) -> UUID:
    return conn.execute(
        text(
            "SELECT id FROM roles WHERE scope = :s AND code = :c AND account_id IS NULL"
        ),
        {"s": scope, "c": code},
    ).scalar_one()


def _permiso(conn, code: str, scope: str) -> None:
    conn.execute(
        text(
            "INSERT INTO permissions (code, description, scope) "
            "VALUES (:c, 'prueba', :s)"
        ),
        {"c": code, "s": scope},
    )


def _usos_en_el_codigo() -> set[tuple[str, str]]:
    """Las llamadas reales a los guards en `app/`, leídas del AST.

    Del AST y no con una expresión regular: un docstring que muestra cómo se
    usa el guard no es un endpoint que exija el permiso.
    """
    usos = set()
    for fichero in RAIZ_APP.rglob("*.py"):
        for nodo in ast.walk(ast.parse(fichero.read_text())):
            if not isinstance(nodo, ast.Call):
                continue
            nombre = getattr(nodo.func, "id", None) or getattr(nodo.func, "attr", None)
            if nombre not in _GUARDS:
                continue
            primero = nodo.args[0] if nodo.args else None
            assert isinstance(primero, ast.Constant) and isinstance(
                primero.value, str
            ), (
                f"{fichero}:{nodo.lineno}: {nombre} con un permiso que no es un "
                f"literal; este test no puede comprobarlo contra el catálogo"
            )
            usos.add((_GUARDS[nombre], primero.value))
    return usos


# ── La siembra ──────────────────────────────────────────────────────────


def test_siembra_los_cuatro_roles_de_sistema_por_alcance(conn):
    filas = conn.execute(text("""
            SELECT scope, code, name FROM roles
             WHERE is_system ORDER BY scope, code
            """)).all()

    esperados = [
        (scope, code, nombre)
        for scope in ("account", "organization")
        for code, nombre in sorted(
            [
                ("admin", "Administrador"),
                ("billing", "Facturación"),
                ("member", "Miembro"),
                ("owner", "Propietario"),
            ]
        )
    ]
    assert [tuple(f) for f in filas] == esperados


def test_los_roles_de_sistema_coinciden_con_los_de_las_membresias(conn):
    """Las membresías guardan el código del rol como texto: si uno no tiene
    fila en `roles`, quien lo tenga se queda sin ningún permiso."""
    from app.models.account_user import AccountRole
    from app.models.organization_user import OrganizationRole

    for scope, enum in (("account", AccountRole), ("organization", OrganizationRole)):
        codigos = set(
            conn.execute(
                text("SELECT code FROM roles WHERE is_system AND scope = :s"),
                {"s": scope},
            ).scalars()
        )
        assert codigos == {r.value for r in enum}


# ── La regla del catálogo ───────────────────────────────────────────────


def test_cada_permiso_que_exige_un_endpoint_esta_en_el_catalogo(conn):
    """Un endpoint que exige un permiso que nadie sembró da 403 a todos."""
    catalogo = {
        (scope, code)
        for code, scope in conn.execute(text("SELECT code, scope FROM permissions"))
    }
    faltan = _usos_en_el_codigo() - catalogo
    assert not faltan, (
        f"permisos exigidos en app/ sin fila (o con otro alcance) en el catálogo: "
        f"{sorted(faltan)}. Van en una migración del mismo PR."
    )


def test_cada_permiso_del_catalogo_lo_exige_un_endpoint(conn):
    """Un permiso que ningún endpoint verifica es un interruptor decorativo."""
    catalogo = {
        (scope, code)
        for code, scope in conn.execute(text("SELECT code, scope FROM permissions"))
    }
    sin_uso = catalogo - _usos_en_el_codigo()
    assert (
        not sin_uso
    ), f"permisos del catálogo que ningún endpoint exige: {sorted(sin_uso)}"


# ── Lo que la base garantiza sola ───────────────────────────────────────


def test_un_rol_de_cuenta_recibe_un_permiso_de_cuenta(conn):
    _permiso(conn, "pruebas.escribir", "account")
    conn.execute(
        text(
            "INSERT INTO role_permissions (role_id, permission_code, scope) "
            "VALUES (:r, 'pruebas.escribir', 'account')"
        ),
        {"r": str(_rol(conn, "account", "owner"))},
    )


def test_un_rol_de_organizacion_no_recibe_un_permiso_de_cuenta(conn):
    """«Owner de la organización puede editar la marca» no es una fila válida."""
    _permiso(conn, "pruebas.escribir", "account")
    with pytest.raises(IntegrityError, match="fk_role_permissions"):
        conn.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_code, scope) "
                "VALUES (:r, 'pruebas.escribir', 'account')"
            ),
            {"r": str(_rol(conn, "organization", "owner"))},
        )


def test_el_alcance_de_la_fila_no_puede_mentir_sobre_el_del_permiso(conn):
    _permiso(conn, "pruebas.escribir", "account")
    with pytest.raises(IntegrityError, match="fk_role_permissions"):
        conn.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_code, scope) "
                "VALUES (:r, 'pruebas.escribir', 'organization')"
            ),
            {"r": str(_rol(conn, "organization", "owner"))},
        )


def test_un_rol_de_sistema_no_tiene_cuenta(conn):
    cuenta = uuid4()
    conn.execute(
        text("INSERT INTO accounts (id, account_name) VALUES (:id, 'Mero Mero')"),
        {"id": str(cuenta)},
    )
    with pytest.raises(IntegrityError, match="ck_roles_sistema_sin_cuenta"):
        conn.execute(
            text(
                "INSERT INTO roles (scope, code, name, account_id, is_system) "
                "VALUES ('account', 'supervisor', 'Supervisor', :c, true)"
            ),
            {"c": str(cuenta)},
        )


def test_un_rol_personalizado_pertenece_a_una_cuenta(conn):
    with pytest.raises(IntegrityError, match="ck_roles_sistema_sin_cuenta"):
        conn.execute(text("""
                INSERT INTO roles (scope, code, name, is_system)
                VALUES ('account', 'supervisor', 'Supervisor', false)
                """))


def test_dos_cuentas_pueden_tener_un_rol_con_el_mismo_codigo(conn):
    """Y una misma cuenta no puede repetirlo."""
    a, b = uuid4(), uuid4()
    for cid in (a, b):
        conn.execute(
            text("INSERT INTO accounts (id, account_name) VALUES (:id, 'X')"),
            {"id": str(cid)},
        )
        conn.execute(
            text(
                "INSERT INTO roles (scope, code, name, account_id) "
                "VALUES ('account', 'supervisor', 'Supervisor', :c)"
            ),
            {"c": str(cid)},
        )
    with pytest.raises(IntegrityError, match="uq_roles_de_cuenta"):
        conn.execute(
            text(
                "INSERT INTO roles (scope, code, name, account_id) "
                "VALUES ('account', 'supervisor', 'Otro', :c)"
            ),
            {"c": str(a)},
        )


def test_no_hay_dos_roles_de_sistema_iguales(conn):
    with pytest.raises(IntegrityError, match="uq_roles_de_sistema"):
        conn.execute(text("""
                INSERT INTO roles (scope, code, name, is_system)
                VALUES ('account', 'owner', 'Otro owner', true)
                """))


@pytest.mark.parametrize("code", ["Branding.Write", "branding", "branding.write.x"])
def test_el_codigo_es_recurso_punto_accion(conn, code):
    with pytest.raises(IntegrityError, match="ck_permissions_code_formato"):
        _permiso(conn, code, "account")


# ── Rollback ────────────────────────────────────────────────────────────


def test_el_downgrade_borra_las_tres_tablas_y_vuelve(engine):
    if desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) != 0:
        raise RuntimeError("fallo el downgrade a la 037")
    try:
        with engine.connect() as c:
            quedan = c.execute(text("""
                    SELECT count(*) FROM information_schema.tables
                     WHERE table_schema = 'public'
                       AND table_name IN ('permissions', 'roles', 'role_permissions')
                    """)).scalar_one()
        assert quedan == 0
    finally:
        if desechable.alembic(BASE, "upgrade", "head") != 0:
            raise RuntimeError("fallo el upgrade de vuelta a head")

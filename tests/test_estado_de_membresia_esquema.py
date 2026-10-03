"""La migracion 034 hace lo que dice: la columna de estado en la membresia.

POR QUE ESTE FICHERO EXISTE APARTE DEL RESTO DE TESTS
=======================================================
Por lo mismo que `test_estado_de_usuario_esquema.py`: lo que prueba no lo
construye `create_all()`, porque el modelo `OrganizationUser` todavia no
declara `status` — la migracion es solo la mitad "expand" (ver su docstring).
El harness normal no conoce esta columna hasta que un modelo la declare.

A diferencia de la 029, esta migracion no trae relleno de datos, asi que no
hace falta el viaje downgrade -> insertar -> upgrade: basta con construir el
esquema en head y comprobar la columna y el CHECK directamente.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests import esquema_desechable as desechable

BASE = "siscom_test_estado_membresia"


@pytest.fixture(scope="module")
def engine():
    """Base desechable con el esquema productivo y las migraciones encima."""
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    """Conexion en una transaccion que siempre se revierte."""
    with engine.connect() as c:
        tx = c.begin()
        try:
            yield c
        finally:
            tx.rollback()


def _cuenta(conn, nombre: str) -> UUID:
    cid = uuid4()
    conn.execute(
        text("INSERT INTO accounts (id, account_name) VALUES (:id, :nombre)"),
        {"id": str(cid), "nombre": nombre},
    )
    return cid


def _organizacion(conn, cuenta: UUID, nombre: str) -> UUID:
    oid = uuid4()
    conn.execute(
        text("""
            INSERT INTO organizations (id, account_id, name)
            VALUES (:id, :cuenta, :nombre)
            """),
        {"id": str(oid), "cuenta": str(cuenta), "nombre": nombre},
    )
    return oid


def _usuario(conn, correo: str, organizacion: UUID) -> UUID:
    uid = uuid4()
    conn.execute(
        text("""
            INSERT INTO users (id, email, default_organization_id, external_id)
            VALUES (:id, :correo, :org, :correo)
            """),
        {"id": str(uid), "correo": correo, "org": str(organizacion)},
    )
    return uid


def _membresia(conn, organizacion: UUID, usuario: UUID, rol: str = "member") -> UUID:
    mid = uuid4()
    conn.execute(
        text("""
            INSERT INTO organization_users (id, organization_id, user_id, role)
            VALUES (:id, :org, :usuario, :rol)
            """),
        {
            "id": str(mid),
            "org": str(organizacion),
            "usuario": str(usuario),
            "rol": rol,
        },
    )
    return mid


def test_columna_status_existe_y_es_obligatoria(conn):
    fila = conn.execute(text("""
            SELECT data_type, is_nullable, column_default
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name   = 'organization_users'
               AND column_name  = 'status'
            """)).one()
    assert fila[0] == "text"
    assert fila[1] == "NO"
    # El DEFAULT es lo que permite que la migracion sea aditiva: el codigo ya
    # desplegado (add_member, invite_user) sigue insertando sin mencionarla.
    assert "ACTIVE" in fila[2]


def test_membresia_nueva_nace_activa(conn):
    cuenta = _cuenta(conn, "Cuenta del default")
    org = _organizacion(conn, cuenta, "Org del default")
    usuario = _usuario(conn, "default@example.com", org)
    mid = _membresia(conn, org, usuario)

    estado = conn.execute(
        text("SELECT status FROM organization_users WHERE id = :id"), {"id": str(mid)}
    ).scalar_one()
    assert estado == "ACTIVE"


def test_el_check_rechaza_un_estado_inventado(conn):
    cuenta = _cuenta(conn, "Cuenta del check")
    org = _organizacion(conn, cuenta, "Org del check")
    usuario = _usuario(conn, "check@example.com", org)
    mid = _membresia(conn, org, usuario)

    with pytest.raises(IntegrityError):
        conn.execute(
            text("UPDATE organization_users SET status = 'SUSPENDED' WHERE id = :id"),
            {"id": str(mid)},
        )


def test_el_check_acepta_inactive(conn):
    """El unico estado distinto de ACTIVE que esta migracion define."""
    cuenta = _cuenta(conn, "Cuenta del inactive")
    org = _organizacion(conn, cuenta, "Org del inactive")
    usuario = _usuario(conn, "inactive@example.com", org)
    mid = _membresia(conn, org, usuario)

    conn.execute(
        text("UPDATE organization_users SET status = 'INACTIVE' WHERE id = :id"),
        {"id": str(mid)},
    )
    estado = conn.execute(
        text("SELECT status FROM organization_users WHERE id = :id"), {"id": str(mid)}
    ).scalar_one()
    assert estado == "INACTIVE"


def test_dos_membresias_de_la_misma_persona_son_independientes(conn):
    """El punto entero de la migracion: acotada a (organization_id, user_id).

    Con una organizacion por persona hoy esto no se ve en produccion, pero es
    la propiedad que el white-label necesita desde el primer dia.
    """
    cuenta = _cuenta(conn, "Cuenta multi-org")
    org_a = _organizacion(cuenta=cuenta, conn=conn, nombre="Org A")
    org_b = _organizacion(cuenta=cuenta, conn=conn, nombre="Org B")
    usuario = _usuario(conn, "multi@example.com", org_a)

    mid_a = _membresia(conn, org_a, usuario)
    mid_b = _membresia(conn, org_b, usuario)

    conn.execute(
        text("UPDATE organization_users SET status = 'INACTIVE' WHERE id = :id"),
        {"id": str(mid_a)},
    )

    estado_a = conn.execute(
        text("SELECT status FROM organization_users WHERE id = :id"),
        {"id": str(mid_a)},
    ).scalar_one()
    estado_b = conn.execute(
        text("SELECT status FROM organization_users WHERE id = :id"),
        {"id": str(mid_b)},
    ).scalar_one()
    assert estado_a == "INACTIVE"
    assert estado_b == "ACTIVE"


def test_downgrade_quita_la_columna_y_upgrade_la_repone(engine):
    if desechable.alembic(BASE, "downgrade", "033_el_esquema_alcanza") != 0:
        raise RuntimeError("fallo el downgrade a la 033")

    with engine.connect() as c:
        columna = c.execute(text("""
                SELECT count(*) FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name   = 'organization_users'
                   AND column_name  = 'status'
                """)).scalar_one()
        assert columna == 0, "el downgrade tiene que quitar la columna"

    if desechable.alembic(BASE, "upgrade", "head") != 0:
        raise RuntimeError("fallo el upgrade a head")

    with engine.connect() as c:
        columna = c.execute(text("""
                SELECT count(*) FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name   = 'organization_users'
                   AND column_name  = 'status'
                """)).scalar_one()
        assert columna == 1, "el segundo upgrade tiene que reponer la columna"

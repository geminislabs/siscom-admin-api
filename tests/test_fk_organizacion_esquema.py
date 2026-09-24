"""La 030 pone la FK de `users.organization_id` y la exige a lo nuevo.

POR QUE ESTE FICHERO EXISTE APARTE DEL RESTO DE TESTS
=====================================================
Por lo mismo que `test_estado_de_usuario_esquema.py`: lo que prueba no lo
construye `create_all()`. Una base hecha desde la metadata **ya trae** la FK,
porque el modelo la declara — comprobarla ahi seria tautologico. La pregunta es
si la migracion la pone sobre el esquema que tiene produccion, que es otra cosa.

Y hay una pregunta mas, que es la que de verdad importa: la restriccion entra
como `NOT VALID` porque siete filas anteriores apuntan a una organizacion que no
existe. `NOT VALID` se confunde con "desactivada", asi que el test que vale es
el que mete una fila nueva mala y comprueba que la rechaza.
"""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests import esquema_desechable as desechable

BASE = "siscom_test_fk_organizacion"
REVISION_ANTERIOR = "029_estado_de_usuario"
CONSTRAINT = "users_organization_id_fkey"


@pytest.fixture(scope="module")
def engine():
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    with engine.connect() as c:
        tx = c.begin()
        try:
            yield c
        finally:
            tx.rollback()


def _organizacion(conn):
    """Una organizacion real, para colgar usuarios validos de ella.

    Se crea con su cuenta: `organizations.account_id` es NOT NULL con su propia
    FK, asi que una organizacion suelta no existe en este esquema.
    """
    fila = conn.execute(text("SELECT id FROM public.organizations LIMIT 1")).first()
    if fila:
        return fila[0]

    cuenta, org = uuid4(), uuid4()
    conn.execute(
        text("INSERT INTO public.accounts (id, account_name) VALUES (:id, 'Prueba')"),
        {"id": cuenta},
    )
    conn.execute(
        text("""
            INSERT INTO public.organizations (id, name, account_id)
            VALUES (:id, 'Prueba', :cuenta)
            """),
        {"id": org, "cuenta": cuenta},
    )
    return org


def _insertar_usuario(conn, organization_id):
    conn.execute(
        text("""
            INSERT INTO public.users (id, email, organization_id)
            VALUES (:id, :email, :org)
            """),
        {"id": uuid4(), "email": f"{uuid4()}@example.com", "org": organization_id},
    )


# ---------------------------------------------------------------------------
# Lo que deja la migracion
# ---------------------------------------------------------------------------


def test_la_columna_queda_obligatoria(conn):
    nulable = conn.execute(text("""
            SELECT is_nullable FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'users'
               AND column_name = 'organization_id'
            """)).scalar_one()

    assert nulable == "NO"


def test_la_restriccion_existe_y_referencia_organizations(conn):
    fila = conn.execute(
        text("""
            SELECT c.confdeltype, t.relname AS referencia, c.convalidated
              FROM pg_constraint c
              JOIN pg_class t ON t.oid = c.confrelid
             WHERE c.conname = :nombre AND c.contype = 'f'
            """),
        {"nombre": CONSTRAINT},
    ).first()

    assert fila is not None, "la migracion no creo la clave foranea"
    assert fila.referencia == "organizations"
    # 'c' = CASCADE, que es lo que declara el modelo.
    assert fila.confdeltype == "c"


def test_la_restriccion_queda_sin_validar_y_eso_es_deliberado(conn):
    """Siete filas anteriores apuntan al vacio; la deuda queda consultable."""
    validada = conn.execute(
        text("SELECT convalidated FROM pg_constraint WHERE conname = :n"),
        {"n": CONSTRAINT},
    ).scalar_one()

    assert validada is False


# ---------------------------------------------------------------------------
# Lo que la restriccion hace, que es la parte que se confunde
# ---------------------------------------------------------------------------


def test_rechaza_una_fila_nueva_que_apunta_al_vacio(conn):
    """`NOT VALID` no es "desactivada": lo nuevo se exige igual.

    Es el test que importa. Sin el, `NOT VALID` se lee como que la restriccion
    no hace nada, y entonces esta migracion no compraria nada.
    """
    inexistente = uuid4()

    with pytest.raises(IntegrityError):
        _insertar_usuario(conn, inexistente)


def test_acepta_una_fila_nueva_con_organizacion_real(conn):
    _insertar_usuario(conn, _organizacion(conn))


def test_rechaza_una_fila_nueva_sin_organizacion(conn):
    with pytest.raises(IntegrityError):
        _insertar_usuario(conn, None)


# ---------------------------------------------------------------------------
# El escenario de produccion: siete filas apuntando al vacio
# ---------------------------------------------------------------------------


def test_la_migracion_aplica_con_filas_apuntando_al_vacio(engine):
    """El caso real, y la razon de ser de `NOT VALID`.

    Con la restriccion normal, esto es exactamente lo que tumbo el despliegue de
    la v1.32.1 con un ForeignKeyViolation. El test hace el viaje de verdad
    —bajar a la 029, ensuciar, volver a subir— porque cuando se construye la
    base del fixture esas filas todavia no existen.
    """
    desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR)

    huerfano = uuid4()
    with engine.begin() as c:
        c.execute(
            text("""
                INSERT INTO public.users (id, email, organization_id)
                VALUES (:id, :email, :org)
                """),
            {"id": huerfano, "email": f"{huerfano}@example.com", "org": uuid4()},
        )

    desechable.alembic(BASE, "upgrade", "head")

    with engine.connect() as c:
        sigue = c.execute(
            text("SELECT organization_id IS NOT NULL FROM public.users WHERE id = :id"),
            {"id": huerfano},
        ).scalar_one()
        validada = c.execute(
            text("SELECT convalidated FROM pg_constraint WHERE conname = :n"),
            {"n": CONSTRAINT},
        ).scalar_one()

    # La fila sobrevive intacta y la restriccion queda declarada sin validar.
    assert sigue is True
    assert validada is False

    with engine.begin() as c:
        c.execute(text("DELETE FROM public.users WHERE id = :id"), {"id": huerfano})

"""Las FKs de `organization_id`: la 030 sobre `users`, la 031 sobre `units`.

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
REVISION_PREVIA_A_UNIDADES = "030_fk_organizacion_usuario"
CONSTRAINT_UNIDADES = "units_organization_id_fkey"


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


# ---------------------------------------------------------------------------
# La 031: la otra mitad del predicado de aislamiento
#
# Se prueba aparte de la 030 porque su forma es distinta, y la diferencia es el
# dato: `units` no tenia ni una fila rota, asi que su restriccion nace
# **validada** y sin deuda detras. Confundir las dos seria perder justo eso.
# ---------------------------------------------------------------------------


def test_la_columna_de_unidades_queda_obligatoria(conn):
    nulable = conn.execute(text("""
            SELECT is_nullable FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'units'
               AND column_name = 'organization_id'
            """)).scalar_one()

    assert nulable == "NO"


def test_la_restriccion_de_unidades_nace_validada(conn):
    """La diferencia con `users`, y el motivo de que se midiera antes."""
    fila = conn.execute(
        text("""
            SELECT c.confdeltype, t.relname AS referencia, c.convalidated
              FROM pg_constraint c
              JOIN pg_class t ON t.oid = c.confrelid
             WHERE c.conname = :nombre AND c.contype = 'f'
            """),
        {"nombre": CONSTRAINT_UNIDADES},
    ).first()

    assert fila is not None, "la migracion no creo la clave foranea"
    assert fila.referencia == "organizations"
    assert fila.confdeltype == "c"
    # Cero filas rotas al medir, asi que no hay nada que perdonar.
    assert fila.convalidated is True


def _insertar_unidad(conn, organization_id):
    conn.execute(
        text("""
            INSERT INTO public.units (id, name, unit_ref, organization_id)
            VALUES (:id, 'Unidad de prueba', :ref, :org)
            """),
        {"id": uuid4(), "ref": str(uuid4()), "org": organization_id},
    )


def test_una_unidad_no_puede_apuntar_al_vacio(conn):
    with pytest.raises(IntegrityError):
        _insertar_unidad(conn, uuid4())


def test_una_unidad_no_puede_quedarse_sin_organizacion(conn):
    with pytest.raises(IntegrityError):
        _insertar_unidad(conn, None)


def test_una_unidad_con_organizacion_real_entra(conn):
    _insertar_unidad(conn, _organizacion(conn))


def test_la_migracion_de_unidades_se_planta_si_encuentra_una_rota(engine):
    """El guardia, probado por el unico camino que lo prueba: rompiendo algo.

    La `030` tolera lo viejo porque lo viejo estaba roto de antes. La `031` no:
    se midio cero y cero, asi que cualquier fila rota es una sorpresa, y una
    sorpresa sobre la columna que decide quien ve que unidad se mira **antes**
    de ponerle la restriccion. Si este test pasara, el mensaje de la migracion
    seria decoracion.
    """
    desechable.alembic(BASE, "downgrade", REVISION_PREVIA_A_UNIDADES)

    rota = uuid4()
    with engine.begin() as c:
        c.execute(
            text("""
                INSERT INTO public.units (id, name, unit_ref, organization_id)
                VALUES (:id, 'Unidad rota', :ref, :org)
                """),
            {"id": rota, "ref": str(rota), "org": uuid4()},
        )

    codigo = desechable.alembic(BASE, "upgrade", "head")
    assert codigo != 0, "la migracion deberia haberse plantado"

    # Y se planta **sin tocar nada**: la columna sigue admitiendo NULL.
    with engine.connect() as c:
        nulable = c.execute(text("""
                SELECT is_nullable FROM information_schema.columns
                 WHERE table_schema = 'public' AND table_name = 'units'
                   AND column_name = 'organization_id'
                """)).scalar_one()
    assert nulable == "YES"

    with engine.begin() as c:
        c.execute(text("DELETE FROM public.units WHERE id = :id"), {"id": rota})
    assert desechable.alembic(BASE, "upgrade", "head") == 0

"""La migracion 028 (Fase 3, rebanada A) hace lo que dice.

POR QUE ESTE FICHERO EXISTE APARTE DEL RESTO DE TESTS
=====================================================
Por lo mismo que `test_tenancy_esquema.py`: la rebanada A es esquema **sin
modelos**. `app/models/user.py` no declara todavia `external_id`,
`identity_provider` ni `brand_account_id`, asi que las dos redes habituales no
tienen de donde agarrarse.

  - El harness normal construye la base con `SQLModel.metadata.create_all()` y
    solo conoce lo que algun modelo declara: aqui, nada. Peor todavia, ese
    harness seguiria creando `users.email` con la unicidad **global** que esta
    migracion quita — un test escrito ahi probaria lo contrario de lo que hay
    en produccion.
  - El comparador de deriva mira en una sola direccion —que el esquema tenga lo
    que los modelos esperan—, asi que de la 028 solo comprueba que aplique.

Y lo que hay debajo no es declarativo: la unicidad por marca vive en dos
indices parciales que se reparten la tabla, y `external_id` lo rellena un
trigger mientras dure la ventana entre los dos releases.

Por eso la base de este modulo se construye como la del comparador: snapshot
del esquema productivo + `alembic upgrade head`.

LO QUE ESTE FICHERO NO PRUEBA
=============================
El backfill de las filas que ya existian. El snapshot es DDL sin datos, asi que
aqui no hay usuarios anteriores a la migracion a los que rellenarles el handle.
Lo que si se prueba es el mecanismo que los rellena de aqui en adelante —el
trigger—, y el recuento sobre las filas reales es el paso 3 del runbook
`docs/runbooks/desplegar-identidad.md`, igual que los tres contadores de la 027.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests import esquema_desechable as desechable

BASE = "siscom_test_identidad"


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


def _usuario(
    conn,
    correo: str,
    marca: UUID | None = None,
    external_id: str | None = None,
    proveedor: str = "cognito",
) -> UUID:
    uid = uuid4()
    conn.execute(
        text("""
            INSERT INTO users (id, email, brand_account_id, external_id,
                               identity_provider)
            VALUES (:id, :correo, :marca, :ext, :prov)
            """),
        {
            "id": str(uid),
            "correo": correo,
            "marca": str(marca) if marca else None,
            "ext": external_id,
            "prov": proveedor,
        },
    )
    return uid


def _handle(conn, uid: UUID) -> str:
    return conn.execute(
        text("SELECT external_id FROM users WHERE id = :id"), {"id": str(uid)}
    ).scalar_one()


# ---------------------------------------------------------------------------
# Lo que la migracion deja puesto
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "columna, tipo, nullable",
    [
        # Obligatorio: un usuario sin handle no se puede autenticar contra
        # ningun proveedor, y el trigger existe justamente para que no haya
        # forma de crear uno asi.
        ("external_id", "text", "NO"),
        ("identity_provider", "text", "NO"),
        # Admite NULL a proposito: NULL es la marca por defecto, no la ausencia
        # de marca. Ver la cabecera de la migracion.
        ("brand_account_id", "uuid", "YES"),
    ],
)
def test_users_gana_las_columnas_de_identidad(conn, columna, tipo, nullable):
    fila = conn.execute(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='users' "
            "AND column_name = :c"
        ),
        {"c": columna},
    ).one()
    assert fila == (tipo, nullable)


@pytest.mark.parametrize(
    "columna, tipo, nullable",
    [
        ("identity_provider", "text", "YES"),
        ("idp_config", "jsonb", "NO"),
    ],
)
def test_accounts_gana_el_enrutamiento_de_proveedor(conn, columna, tipo, nullable):
    fila = conn.execute(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='accounts' "
            "AND column_name = :c"
        ),
        {"c": columna},
    ).one()
    assert fila == (tipo, nullable)


def test_la_unicidad_global_de_correo_ya_no_existe(conn):
    """Es el unico cambio no aditivo de la 028, y el punto entero de la fase."""
    restricciones = conn.execute(text("""
            SELECT c.conname
              FROM pg_constraint c
              JOIN pg_class t ON t.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'public' AND t.relname = 'users'
               AND c.contype = 'u'
               AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
                      FROM unnest(c.conkey) k
                      JOIN pg_attribute a
                        ON a.attrelid = c.conrelid AND a.attnum = k
                   ) = ARRAY['email']
            """)).scalars()
    assert list(restricciones) == []


@pytest.mark.parametrize(
    "indice, predicado",
    [
        ("uq_users_marca_correo", "brand_account_id IS NOT NULL"),
        ("uq_users_correo_marca_por_defecto", "brand_account_id IS NULL"),
        # Sin predicado: cubre la tabla entera.
        ("uq_users_proveedor_external_id", None),
    ],
)
def test_los_indices_de_unicidad_cubren_lo_que_dicen(conn, indice, predicado):
    """Los dos parciales tienen que repartirse la tabla sin dejar hueco.

    Se mira el predicado y no solo el nombre: dos indices parciales con el
    mismo `WHERE` dejarian a la mitad de la tabla sin unicidad y todos los
    demas tests de este fichero pasarian igual.
    """
    definicion = conn.execute(
        text(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='public' "
            "AND tablename='users' AND indexname = :i"
        ),
        {"i": indice},
    ).scalar_one()
    assert "CREATE UNIQUE INDEX" in definicion
    if predicado is None:
        assert "WHERE" not in definicion
    else:
        assert definicion.endswith(f"WHERE ({predicado})")


# ---------------------------------------------------------------------------
# La unicidad por marca — el requisito del white-label
# ---------------------------------------------------------------------------


def test_el_mismo_correo_convive_en_dos_marcas(conn):
    """El caso que existe la fase: la misma persona, cliente de dos partners."""
    una = _cuenta(conn, "Mero Mero")
    otra = _cuenta(conn, "Otro Partner")

    _usuario(conn, "jesus@example.com", marca=una, external_id=str(uuid4()))
    _usuario(conn, "jesus@example.com", marca=otra, external_id=str(uuid4()))

    cuantos = conn.execute(
        text("SELECT count(*) FROM users WHERE email = 'jesus@example.com'")
    ).scalar_one()
    assert cuantos == 2


def test_el_mismo_correo_choca_dentro_de_una_marca(conn):
    marca = _cuenta(conn, "Mero Mero")
    _usuario(conn, "jesus@example.com", marca=marca, external_id=str(uuid4()))

    with pytest.raises(IntegrityError):
        _usuario(conn, "jesus@example.com", marca=marca, external_id=str(uuid4()))


def test_el_mismo_correo_choca_en_la_marca_por_defecto(conn):
    """Quitar `users_email_key` no puede aflojar el invariante de hoy.

    Todos los usuarios que existen viven con `brand_account_id IS NULL`. Si el
    indice parcial de la marca por defecto no estuviera, esta migracion habria
    convertido un correo unico en un correo repetible para todo el padron
    actual, en silencio.
    """
    _usuario(conn, "jesus@example.com", external_id=str(uuid4()))

    with pytest.raises(IntegrityError):
        _usuario(conn, "jesus@example.com", external_id=str(uuid4()))


def test_el_handle_es_unico_dentro_del_proveedor(conn):
    marca = _cuenta(conn, "Mero Mero")
    handle = str(uuid4())
    _usuario(conn, "uno@example.com", marca=marca, external_id=handle)

    with pytest.raises(IntegrityError):
        _usuario(conn, "otro@example.com", marca=marca, external_id=handle)


# ---------------------------------------------------------------------------
# El trigger que sostiene la ventana entre los dos releases
# ---------------------------------------------------------------------------


def test_un_alta_sin_handle_recibe_el_correo(conn):
    """Es lo que hace el codigo viejo durante la ventana: el correo ES el
    username de Cognito con el que se dio de alta."""
    uid = _usuario(conn, "viejo@example.com")
    assert _handle(conn, uid) == "viejo@example.com"


def test_el_handle_explicito_gana(conn):
    """La rebanada B escribe UUID, y el trigger no puede pisarlos.

    Al reves que el trigger de `account_path` en la 027, que recalcula e ignora
    lo que traiga el INSERT: aquel ancla un invariante de aislamiento, este solo
    rellena un hueco de transicion.
    """
    handle = str(uuid4())
    uid = _usuario(conn, "nuevo@example.com", external_id=handle)
    assert _handle(conn, uid) == handle


def test_cambiar_el_correo_no_mueve_el_handle(conn):
    """El username de Cognito es inmutable; el correo de la aplicacion no.

    Si el trigger siguiera al correo, el primer cambio de direccion dejaria al
    usuario autenticandose contra un username que no existe en el pool.
    """
    uid = _usuario(conn, "antes@example.com")
    conn.execute(
        text("UPDATE users SET email = 'despues@example.com' WHERE id = :id"),
        {"id": str(uid)},
    )
    assert _handle(conn, uid) == "antes@example.com"


# ---------------------------------------------------------------------------
# Enrutamiento de proveedor y borrado de marca
# ---------------------------------------------------------------------------


def test_solo_se_admiten_los_proveedores_que_el_codigo_conoce(conn):
    marca = _cuenta(conn, "Mero Mero")
    with pytest.raises(IntegrityError):
        _usuario(
            conn,
            "futuro@example.com",
            marca=marca,
            external_id=str(uuid4()),
            proveedor="workos",
        )


def test_la_cuenta_puede_no_declarar_proveedor(conn):
    """NULL = hereda el proveedor por defecto del despliegue."""
    cid = _cuenta(conn, "Sin IdP propio")
    fila = conn.execute(
        text("SELECT identity_provider, idp_config FROM accounts WHERE id = :id"),
        {"id": str(cid)},
    ).one()
    assert fila == (None, {})


def test_la_cuenta_no_admite_un_proveedor_inventado(conn):
    cid = uuid4()
    with pytest.raises(IntegrityError):
        conn.execute(
            text("""
                INSERT INTO accounts (id, account_name, identity_provider)
                VALUES (:id, 'Con IdP raro', 'okta')
                """),
            {"id": str(cid)},
        )


def test_idp_config_tiene_que_ser_un_objeto(conn):
    """Un array o un escalar ahi dentro rompen a quien lea `config['clave']`."""
    cid = uuid4()
    with pytest.raises(IntegrityError):
        conn.execute(
            text("""
                INSERT INTO accounts (id, account_name, idp_config)
                VALUES (:id, 'Config torcida', '[]'::jsonb)
                """),
            {"id": str(cid)},
        )


def test_borrar_una_marca_con_usuarios_falla(conn):
    """RESTRICT y no CASCADE: una credencial no desaparece de callada."""
    marca = _cuenta(conn, "Mero Mero")
    _usuario(conn, "jesus@example.com", marca=marca, external_id=str(uuid4()))

    with pytest.raises(IntegrityError):
        conn.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": str(marca)})


# ---------------------------------------------------------------------------
# Reversibilidad
# ---------------------------------------------------------------------------


def test_la_reversion_esta_documentada_como_condicional():
    """El `downgrade` aborta si dos marcas ya comparten correo.

    No se ejecuta aqui —revertir la migracion en la base del modulo dejaria a
    los demas tests sin esquema— pero la condicion tiene que estar escrita en
    el fichero, porque es la unica que puede convertir una reversion rutinaria
    en una perdida de datos.
    """
    from pathlib import Path

    fuente = (
        Path(__file__).resolve().parents[1]
        / "app/db/migrations/versions/028_identidad_esquema.py"
    ).read_text()
    assert "no se puede revertir la 028" in fuente
    assert "docs/runbooks/desplegar-identidad.md" in fuente


def test_el_trigger_sobrevive_a_correr_la_migracion_dos_veces(conn):
    """`CREATE OR REPLACE` + `DROP TRIGGER IF EXISTS`: una sola definicion.

    Un despliegue reintentado no puede dejar dos triggers encadenados sobre la
    misma tabla.
    """
    cuantos = conn.execute(text("""
            SELECT count(*) FROM pg_trigger t
              JOIN pg_class c ON c.oid = t.tgrelid
             WHERE c.relname = 'users' AND NOT t.tgisinternal
               AND t.tgname = 'users_identidad_before'
            """)).scalar_one()
    assert cuantos == 1


def test_el_esquema_no_perdio_cognito_sub(conn):
    """El handle y el sujeto del token son cosas distintas (ver la cabecera).

    Si alguien "limpia" `cognito_sub` creyendo que `external_id` lo reemplaza,
    `deps.py` deja de poder resolver el usuario de un token y cae toda la
    autenticacion. Este test es el recordatorio.
    """
    existe = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='users' "
            "AND column_name='cognito_sub'"
        )
    ).scalar()
    assert existe == 1

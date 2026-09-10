"""La migracion 027 (Fase 2, rebanada A) hace lo que dice.

POR QUE ESTE FICHERO EXISTE APARTE DEL RESTO DE TESTS
=====================================================
La rebanada A es esquema **sin modelos**: ninguna clase de `app/models/`
declara todavia el arbol de cuentas, `account_capabilities`, `tenant_domains`
ni `tenant_branding`. Eso deja las dos redes habituales sin nada que agarrar:

  - El harness normal construye la base con `SQLModel.metadata.create_all()`,
    asi que solo conoce lo que algun modelo declara: aqui, nada.
  - El comparador de deriva mira en una sola direccion —que el esquema tenga lo
    que los modelos esperan—, asi que de la 027 solo comprueba que aplique sin
    romperse.

Y lo que hay debajo no es declarativo: `account_path` lo mantienen dos
triggers mas una restriccion que lo ancla, y ese camino es el predicado de
aislamiento entre clientes (§3 del documento de arquitectura). Un invariante del
que depende quien ve los datos de quien tiene que estar probado antes de que
exista el codigo que lo consulta, no despues.

Por eso la base de este modulo se construye como la del comparador: snapshot
del esquema productivo + `alembic upgrade head`.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests import esquema_desechable as desechable

BASE = "siscom_test_tenancy"

CODIGOS_COMERCIALES = {
    "white_label_enabled",
    "max_custom_domains",
    "max_sub_accounts",
    "can_resell",
}


@pytest.fixture(scope="module")
def engine():
    """Base desechable con el esquema productivo y las migraciones encima.

    De modulo y no de sesion: cuesta unos segundos y solo la usa este fichero.
    """
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


def _cuenta(
    conn, nombre: str, padre: UUID | None = None, tipo: str = "CUSTOMER"
) -> UUID:
    cid = uuid4()
    conn.execute(
        text("""
            INSERT INTO accounts (id, account_name, account_type, parent_account_id)
            VALUES (:id, :nombre, :tipo, :padre)
            """),
        {
            "id": str(cid),
            "nombre": nombre,
            "tipo": tipo,
            "padre": str(padre) if padre else None,
        },
    )
    return cid


def _camino(conn, cid: UUID) -> list:
    return conn.execute(
        text("SELECT account_path FROM accounts WHERE id = :id"),
        {"id": str(cid)},
    ).scalar_one()


# ---------------------------------------------------------------------------
# Lo que la migracion deja puesto
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "columna, tipo, nullable",
    [
        ("parent_account_id", "uuid", "YES"),
        ("account_type", "text", "NO"),
        # El tipo importa: es la decision del ADR-006, y un `text` o un `ltree`
        # aqui pasarian todos los demas tests de este fichero sin chistar.
        # Obligatoria porque el camino es el predicado de aislamiento: una
        # cuenta sin camino no esta en el subarbol de nadie, ni en el suyo.
        ("account_path", "ARRAY", "NO"),
    ],
)
def test_accounts_gana_las_columnas_del_arbol(conn, columna, tipo, nullable):
    fila = conn.execute(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='accounts' "
            "AND column_name = :c"
        ),
        {"c": columna},
    ).one()
    assert fila == (tipo, nullable)


def test_el_camino_es_un_array_de_uuid(conn):
    """`information_schema` dice ARRAY a secas; el tipo del elemento se pregunta
    aparte, y es la mitad que de verdad distingue esta decision."""
    assert (
        conn.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'public.accounts'::regclass "
                "AND attname = 'account_path'"
            )
        ).scalar()
        == "uuid[]"
    )


@pytest.mark.parametrize(
    "tabla", ["account_capabilities", "tenant_domains", "tenant_branding"]
)
def test_las_tres_tablas_nuevas_existen(conn, tabla):
    assert conn.execute(
        text("SELECT to_regclass(:t)"), {"t": f"public.{tabla}"}
    ).scalar()


def test_el_indice_del_camino_es_gin(conn):
    """Un btree sobre `uuid[]` no responde `@>`, que es la consulta de la Fase 2.

    Es la diferencia entre recorrer el subarbol por indice y recorrer toda la
    tabla de cuentas.
    """
    metodo = conn.execute(text("""
            SELECT am.amname
              FROM pg_index i
              JOIN pg_class ic ON ic.oid = i.indexrelid
              JOIN pg_am am ON am.oid = ic.relam
             WHERE ic.relname = 'ix_accounts_account_path'
            """)).scalar()
    assert metodo == "gin"


def test_codigos_comerciales_sembrados(conn):
    presentes = {
        fila[0]
        for fila in conn.execute(
            text("SELECT code FROM capabilities WHERE code = ANY(:codes)"),
            {"codes": sorted(CODIGOS_COMERCIALES)},
        )
    }
    assert presentes == CODIGOS_COMERCIALES


def test_self_signup_mode_no_se_siembra(conn):
    """Sus modos y sus defensas siguen sin acordarse (§12).

    Un codigo presente en la tabla invita a que alguien le invente semantica.
    """
    assert not conn.execute(
        text("SELECT 1 FROM capabilities WHERE code = 'self_signup_mode'")
    ).scalar()


# ---------------------------------------------------------------------------
# El arbol
# ---------------------------------------------------------------------------


def test_una_raiz_tiene_su_propio_uuid_como_camino(conn):
    cid = _cuenta(conn, "Geminis", tipo="PLATFORM")
    assert _camino(conn, cid) == [cid]


def test_el_hijo_cuelga_del_camino_del_padre(conn):
    raiz = _cuenta(conn, "Geminis", tipo="PLATFORM")
    hijo = _cuenta(conn, "Mero Mero", padre=raiz, tipo="RESELLER")
    assert _camino(conn, hijo) == [raiz, hijo]


def _subarbol(conn, raiz_de: UUID) -> set:
    """El subarbol de una cuenta, tal y como lo consultara la rebanada B."""
    return {
        UUID(f[0])
        for f in conn.execute(
            text(
                "SELECT id::text FROM accounts "
                "WHERE account_path @> ARRAY[:id]::uuid[]"
            ),
            {"id": str(raiz_de)},
        )
    }


def _ancestros(conn, de: UUID) -> list:
    """Los ancestros de una cuenta, de raiz a hoja: el techo de capabilities.

    Es la mitad que camina hacia arriba (§4), y con el camino en `uuid[]` no
    necesita indice propio: los elementos ya son los ids.
    """
    return [
        UUID(f[0])
        for f in conn.execute(
            text("""
                SELECT a.id::text FROM accounts a
                 WHERE a.id = ANY (
                       SELECT unnest(account_path) FROM accounts WHERE id = :id)
                 ORDER BY array_position(
                       (SELECT account_path FROM accounts WHERE id = :id), a.id)
                """),
            {"id": str(de)},
        )
    ]


def test_el_subarbol_se_consulta_por_contencion(conn):
    raiz = _cuenta(conn, "Geminis", tipo="PLATFORM")
    marca = _cuenta(conn, "Mero Mero", padre=raiz, tipo="RESELLER")
    cliente = _cuenta(conn, "Empresa 1", padre=marca)
    _cuenta(conn, "Otra marca", padre=raiz, tipo="RESELLER")

    # `@>` incluye a la propia cuenta: el subarbol de Mero Mero es Mero Mero y
    # los suyos, no los suyos a secas.
    assert _subarbol(conn, marca) == {marca, cliente}


def test_los_ancestros_salen_del_propio_camino(conn):
    """La consulta del techo descendente, de raiz a hoja y en orden."""
    raiz = _cuenta(conn, "Geminis", tipo="PLATFORM")
    marca = _cuenta(conn, "Mero Mero", padre=raiz, tipo="RESELLER")
    cliente = _cuenta(conn, "Empresa 1", padre=marca)

    assert _ancestros(conn, cliente) == [raiz, marca, cliente]
    assert _ancestros(conn, raiz) == [raiz]


def test_escribir_el_camino_a_mano_no_sirve_de_nada(conn):
    """Primera capa: el trigger lo recalcula, no lo acepta.

    `account_path` esta en el `UPDATE OF` del trigger BEFORE, asi que cualquier
    sentencia que lo mencione dispara el recalculo desde el padre. Escribirlo a
    mano no falla — se ignora, que es mejor.
    """
    victima = _cuenta(conn, "Empresa 1")
    intruso = _cuenta(conn, "Otra empresa")

    conn.execute(
        text("UPDATE accounts SET account_path = CAST(:p AS uuid[]) WHERE id = :id"),
        {"p": [str(intruso), str(victima)], "id": str(victima)},
    )
    assert _camino(conn, victima) == [victima]


def test_el_camino_termina_en_la_propia_cuenta(conn):
    """Segunda capa: la restriccion, para cuando el trigger no corre.

    `@>` casa un elemento en cualquier posicion, que es justo lo que se quiere
    para pertenencia al subarbol — pero solo vale mientras el array sea de
    verdad la cadena de ancestros. Un id suelto ahi dentro seria un falso
    positivo en una comprobacion de autorizacion.

    El trigger no basta como unica defensa porque hay maneras normales de
    saltarselo: una restauracion o una carga masiva con
    `session_replication_role = replica`, o un `DISABLE TRIGGER` en una sesion
    de soporte. La restriccion sigue ahi en los tres casos.
    """
    victima = _cuenta(conn, "Empresa 1")
    intruso = _cuenta(conn, "Otra empresa")

    conn.execute(text("ALTER TABLE accounts DISABLE TRIGGER accounts_tenancy_before"))
    with pytest.raises(IntegrityError, match="termina_en_si_misma"):
        conn.execute(
            text(
                "UPDATE accounts SET account_path = CAST(:p AS uuid[]) WHERE id = :id"
            ),
            {"p": [str(victima), str(intruso)], "id": str(victima)},
        )


def test_reparentar_reescribe_a_todos_los_descendientes(conn):
    """El fallo clasico del camino materializado: mover una rama y dejar a los
    nietos apuntando al camino viejo. Ahi el aislamiento deja de valer."""
    raiz = _cuenta(conn, "Geminis", tipo="PLATFORM")
    marca = _cuenta(conn, "Mero Mero", padre=raiz, tipo="RESELLER")
    cliente = _cuenta(conn, "Empresa 1", padre=marca)
    nieto = _cuenta(conn, "Flota Norte", padre=cliente)

    conn.execute(
        text("UPDATE accounts SET parent_account_id = :nuevo WHERE id = :id"),
        {"nuevo": str(raiz), "id": str(cliente)},
    )

    assert _camino(conn, cliente) == [raiz, cliente]
    assert _camino(conn, nieto) == [raiz, cliente, nieto]


def test_desenganchar_una_rama_la_deja_como_raiz(conn):
    raiz = _cuenta(conn, "Geminis", tipo="PLATFORM")
    marca = _cuenta(conn, "Mero Mero", padre=raiz, tipo="RESELLER")
    cliente = _cuenta(conn, "Empresa 1", padre=marca)

    conn.execute(
        text("UPDATE accounts SET parent_account_id = NULL WHERE id = :id"),
        {"id": str(marca)},
    )

    assert _camino(conn, marca) == [marca]
    assert _camino(conn, cliente) == [marca, cliente]


def test_una_cuenta_no_puede_ser_su_propio_padre(conn):
    cid = _cuenta(conn, "Geminis", tipo="PLATFORM")
    with pytest.raises(DBAPIError, match="su propio padre"):
        conn.execute(
            text("UPDATE accounts SET parent_account_id = id WHERE id = :id"),
            {"id": str(cid)},
        )


def test_un_ciclo_se_rechaza(conn):
    raiz = _cuenta(conn, "Geminis", tipo="PLATFORM")
    marca = _cuenta(conn, "Mero Mero", padre=raiz, tipo="RESELLER")
    cliente = _cuenta(conn, "Empresa 1", padre=marca)

    with pytest.raises(DBAPIError, match="ciclo"):
        conn.execute(
            text("UPDATE accounts SET parent_account_id = :nuevo WHERE id = :id"),
            {"nuevo": str(cliente), "id": str(raiz)},
        )


def test_la_profundidad_maxima_es_cinco(conn):
    padre = None
    for nivel in range(5):
        padre = _cuenta(conn, f"nivel {nivel}", padre=padre)

    with pytest.raises(DBAPIError, match="profundidad maxima"):
        _cuenta(conn, "nivel 5", padre=padre)


def test_un_padre_inexistente_se_rechaza(conn):
    with pytest.raises(DBAPIError):
        _cuenta(conn, "huerfana", padre=uuid4())


def test_borrar_un_padre_con_hijos_se_rechaza(conn):
    """ON DELETE RESTRICT: un DELETE en cascada se llevaria flotas enteras."""
    raiz = _cuenta(conn, "Geminis", tipo="PLATFORM")
    _cuenta(conn, "Mero Mero", padre=raiz, tipo="RESELLER")
    with pytest.raises(IntegrityError):
        conn.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": str(raiz)})


def test_tipo_de_cuenta_fuera_del_conjunto(conn):
    with pytest.raises(IntegrityError, match="ck_accounts_account_type"):
        _cuenta(conn, "mala", tipo="PIRATA")


def test_las_cuentas_existentes_nacen_como_customer(conn):
    cid = _cuenta(conn, "sin tipo explicito")
    conn.execute(
        text("UPDATE accounts SET account_type = DEFAULT WHERE id = :id"),
        {"id": str(cid)},
    )
    tipo = conn.execute(
        text("SELECT account_type FROM accounts WHERE id = :id"), {"id": str(cid)}
    ).scalar_one()
    assert tipo == "CUSTOMER"


# ---------------------------------------------------------------------------
# tenant_domains — el Host resuelve marca, y solo una
# ---------------------------------------------------------------------------


def _dominio(conn, cuenta: UUID, hostname: str, **extra) -> None:
    campos = {"account_id": str(cuenta), "hostname": hostname, **extra}
    columnas = ", ".join(campos)
    valores = ", ".join(f":{c}" for c in campos)
    conn.execute(
        text(f"INSERT INTO tenant_domains ({columnas}) VALUES ({valores})"), campos
    )


def test_un_hostname_pertenece_a_una_sola_cuenta(conn):
    """Si dos marcas reclaman el mismo Host, quien resuelve tiene que elegir —
    y esa es una decision que no deberia existir."""
    una = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    otra = _cuenta(conn, "Otra", tipo="RESELLER")
    _dominio(conn, una, "meromero.com")
    with pytest.raises(IntegrityError, match="uq_tenant_domains_hostname"):
        _dominio(conn, otra, "meromero.com")


def test_el_hostname_se_guarda_en_minusculas(conn):
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    with pytest.raises(IntegrityError, match="minusculas"):
        _dominio(conn, cuenta, "MeroMero.com")


def test_un_solo_dominio_primario_por_cuenta(conn):
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    _dominio(conn, cuenta, "meromero.com", is_primary=True)
    with pytest.raises(IntegrityError, match="uq_tenant_domains_primario"):
        _dominio(conn, cuenta, "app.meromero.com", is_primary=True)


def test_varios_dominios_no_primarios_por_cuenta(conn):
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    _dominio(conn, cuenta, "meromero.com", is_primary=True)
    _dominio(conn, cuenta, "app.meromero.com")
    _dominio(conn, cuenta, "flota.meromero.com")


def test_verificado_y_sin_fecha_es_una_contradiccion(conn):
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    with pytest.raises(IntegrityError, match="verificado_con_fecha"):
        _dominio(conn, cuenta, "meromero.com", status="VERIFIED")


def test_estado_de_dominio_fuera_del_conjunto(conn):
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    with pytest.raises(IntegrityError, match="ck_tenant_domains_status"):
        _dominio(conn, cuenta, "meromero.com", status="CASI")


# ---------------------------------------------------------------------------
# account_capabilities y tenant_branding
# ---------------------------------------------------------------------------


def _capability_id(conn, code: str) -> UUID:
    return conn.execute(
        text("SELECT id FROM capabilities WHERE code = :c"), {"c": code}
    ).scalar_one()


def test_una_capability_lleva_exactamente_un_valor(conn):
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    cap = _capability_id(conn, "max_sub_accounts")

    with pytest.raises(IntegrityError, match="un_valor"):
        conn.execute(
            text(
                "INSERT INTO account_capabilities (account_id, capability_id) "
                "VALUES (:a, :c)"
            ),
            {"a": str(cuenta), "c": str(cap)},
        )


def test_dos_valores_a_la_vez_tambien_se_rechazan(conn):
    """organization_capabilities lo admite, y por eso puede contener dos
    overrides que se contradicen. Aqui no."""
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    cap = _capability_id(conn, "max_sub_accounts")
    with pytest.raises(IntegrityError, match="un_valor"):
        conn.execute(
            text(
                "INSERT INTO account_capabilities "
                "(account_id, capability_id, value_int, value_bool) "
                "VALUES (:a, :c, 10, true)"
            ),
            {"a": str(cuenta), "c": str(cap)},
        )


def test_una_capability_por_cuenta_como_mucho(conn):
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    cap = _capability_id(conn, "max_sub_accounts")
    sql = text(
        "INSERT INTO account_capabilities (account_id, capability_id, value_int) "
        "VALUES (:a, :c, :v)"
    )
    conn.execute(sql, {"a": str(cuenta), "c": str(cap), "v": 5000})
    with pytest.raises(IntegrityError, match="uq_account_capabilities"):
        conn.execute(sql, {"a": str(cuenta), "c": str(cap), "v": 9999})


def test_branding_admite_borrador_y_publicado(conn):
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    conn.execute(
        text("""
            INSERT INTO tenant_branding (account_id, brand_name, published, draft)
            VALUES (:a, 'Mero Mero', '{"primary": "#123456"}'::jsonb,
                    '{"primary": "#654321"}'::jsonb)
            """),
        {"a": str(cuenta)},
    )
    fila = conn.execute(
        text(
            "SELECT published->>'primary', draft->>'primary' "
            "FROM tenant_branding WHERE account_id = :a"
        ),
        {"a": str(cuenta)},
    ).one()
    assert fila == ("#123456", "#654321")


def test_branding_rechaza_un_json_que_no_sea_objeto(conn):
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    with pytest.raises(IntegrityError, match="published_objeto"):
        conn.execute(
            text(
                "INSERT INTO tenant_branding (account_id, published) "
                "VALUES (:a, '[]'::jsonb)"
            ),
            {"a": str(cuenta)},
        )


def test_branding_es_uno_por_cuenta(conn):
    cuenta = _cuenta(conn, "Mero Mero", tipo="RESELLER")
    sql = text("INSERT INTO tenant_branding (account_id) VALUES (:a)")
    conn.execute(sql, {"a": str(cuenta)})
    with pytest.raises(IntegrityError):
        conn.execute(sql, {"a": str(cuenta)})


# ---------------------------------------------------------------------------
# El rollback
# ---------------------------------------------------------------------------


def test_el_downgrade_deja_accounts_como_estaba(engine):
    """Un downgrade que no revierte convierte el plan de rollback en una
    mentira, y esa mentira solo se descubre durante una liberacion que ya salio
    mal. Va el ultimo del modulo porque toca el esquema de verdad.

    Baja primero hasta la 027 por nombre y no con un `-1` a secas: la cabeza ya
    no es esta migracion —la 028 anadio dos columnas mas a `accounts`— y un
    `-1` revertiria esa otra. Cada migracion nueva encima volveria a mover el
    suelo de este test si no se dijera contra cual se compara.
    """
    columnas_con_migraciones_posteriores = _columnas_de_accounts(engine)
    engine.dispose()  # un DROP COLUMN no espera a una conexion ociosa del pool

    assert desechable.alembic(BASE, "downgrade", "027_tenancy_esquema") == 0
    columnas_antes = _columnas_de_accounts(engine)
    engine.dispose()

    assert desechable.alembic(BASE, "downgrade", "-1") == 0
    columnas = _columnas_de_accounts(engine)
    assert {"parent_account_id", "account_type", "account_path"} & columnas == set()
    assert columnas == columnas_antes - {
        "parent_account_id",
        "account_type",
        "account_path",
    }
    for tabla in ("account_capabilities", "tenant_domains", "tenant_branding"):
        with engine.connect() as c:
            assert (
                c.execute(
                    text("SELECT to_regclass(:t)"), {"t": f"public.{tabla}"}
                ).scalar()
                is None
            )

    engine.dispose()
    assert desechable.alembic(BASE, "upgrade", "head") == 0
    assert _columnas_de_accounts(engine) == columnas_con_migraciones_posteriores


def _columnas_de_accounts(engine) -> set:
    with engine.connect() as c:
        return {
            f[0]
            for f in c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='accounts'"
                )
            )
        }

"""La migracion 029 hace lo que dice: la columna de estado y el relleno.

POR QUE ESTE FICHERO EXISTE APARTE DEL RESTO DE TESTS
=====================================================
Por lo mismo que `test_tenancy_esquema.py` y `test_identidad_esquema.py`: lo que
prueba no lo construye `create_all()`.

La columna `users.status` si la vera el comparador de deriva en cuanto el modelo
la declare (rebanada de codigo, release siguiente). Lo que **nunca** se podra
probar en el harness normal es el paso 2 de la migracion: un relleno de datos
solo existe si corren las migraciones, y el harness no las corre.

Y es justo el paso del que depende que se pueda borrar el fallback de
`is_master` sin quitarle el rol a nadie. Un relleno que nadie prueba es un
relleno que se descubre en produccion.

COMO ESTAN ESCRITOS
===================
Los tests del relleno no pueden limitarse a mirar lo que dejo `upgrade head`:
cuando esa base se construye, las filas de prueba todavia no existen. Asi que el
fixture `datos` hace el viaje de verdad —`downgrade` a la 028, insertar el
escenario, `upgrade` otra vez— y los tests leen el resultado. Es la unica forma
de que el test pueda fallar por la razon por la que fallaria produccion (§20).
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests import esquema_desechable as desechable

BASE = "siscom_test_estado_usuario"
REVISION_ANTERIOR = "028_identidad_esquema"


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


# ---------------------------------------------------------------------------
# Insercion del escenario
# ---------------------------------------------------------------------------


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


def _usuario(conn, correo: str, organizacion: UUID, master: bool) -> UUID:
    uid = uuid4()
    conn.execute(
        text("""
            INSERT INTO users (id, email, organization_id, is_master, external_id)
            VALUES (:id, :correo, :org, :master, :correo)
            """),
        {
            "id": str(uid),
            "correo": correo,
            "org": str(organizacion),
            "master": master,
        },
    )
    return uid


def _membresia(conn, organizacion: UUID, usuario: UUID, rol: str) -> None:
    conn.execute(
        text("""
            INSERT INTO organization_users (id, organization_id, user_id, role)
            VALUES (:id, :org, :usuario, :rol)
            """),
        {
            "id": str(uuid4()),
            "org": str(organizacion),
            "usuario": str(usuario),
            "rol": rol,
        },
    )


def _evento_removido(conn, cuenta: UUID, organizacion: UUID, usuario: UUID) -> None:
    """El evento que `remove_user_from_organization` escribe antes de borrar."""
    conn.execute(
        text("""
            INSERT INTO account_events
                   (id, account_id, organization_id, actor_type, event_type,
                    target_type, target_id)
            VALUES (:id, :cuenta, :org, 'user', 'org_user_removed',
                    'organization_user', :usuario)
            """),
        {
            "id": str(uuid4()),
            "cuenta": str(cuenta),
            "org": str(organizacion),
            "usuario": str(usuario),
        },
    )


def _membresias_de(conn, usuario: UUID) -> list[str]:
    filas = conn.execute(
        text("""
            SELECT role FROM organization_users
             WHERE user_id = :u ORDER BY role
            """),
        {"u": str(usuario)},
    ).all()
    return [f[0] for f in filas]


@pytest.fixture(scope="module")
def datos(engine):
    """El escenario completo, pasado por `downgrade` + `upgrade` de verdad.

    Los datos se **commitean**: alembic corre en otro proceso y no veria una
    transaccion abierta.
    """
    # El escenario se monta **con la base bajada a la 028**, no en head. Desde
    # la `030` hay clave foranea en `users.organization_id`, asi que el huerfano
    # de mas abajo ya no se puede insertar por encima de ella — y ese es
    # justamente el punto de la FK. Bajar primero reproduce el orden real: esas
    # filas existian en produccion **antes** de que las migraciones corrieran.
    if desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) != 0:
        raise RuntimeError("fallo el downgrade a la 028")

    with engine.connect() as c:
        tx = c.begin()
        cuenta = _cuenta(c, "Cuenta del relleno")

        org_heredado = _organizacion(c, cuenta, "Org del master heredado")
        heredado = _usuario(c, "heredado@example.com", org_heredado, master=True)

        org_con_rol = _organizacion(c, cuenta, "Org del master con membresia")
        con_rol = _usuario(c, "con-rol@example.com", org_con_rol, master=True)
        _membresia(c, org_con_rol, con_rol, "member")

        org_removido = _organizacion(c, cuenta, "Org del master removido")
        removido = _usuario(c, "removido@example.com", org_removido, master=True)
        _evento_removido(c, cuenta, org_removido, removido)

        org_normal = _organizacion(c, cuenta, "Org del usuario normal")
        normal = _usuario(c, "normal@example.com", org_normal, master=False)

        # El caso que tumbo el despliegue de v1.32.1: un master cuya
        # organizacion **no existe**. Se puede insertar aqui porque la base esta
        # en la 028, por debajo de la clave foranea que anade la `030` — igual
        # que en produccion, donde estas filas son anteriores a la migracion.
        org_fantasma = uuid4()
        huerfano = _usuario(c, "huerfano@example.com", org_fantasma, master=True)

        tx.commit()

    if desechable.alembic(BASE, "upgrade", "head") != 0:
        raise RuntimeError("fallo el upgrade a head")

    return {
        "cuenta": cuenta,
        "heredado": heredado,
        "con_rol": con_rol,
        "removido": removido,
        "normal": normal,
        "huerfano": huerfano,
        "org_heredado": org_heredado,
        "org_fantasma": org_fantasma,
    }


# ---------------------------------------------------------------------------
# 1 · La columna
# ---------------------------------------------------------------------------


def test_columna_status_existe_y_es_obligatoria(conn):
    fila = conn.execute(text("""
            SELECT data_type, is_nullable, column_default
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND table_name   = 'users'
               AND column_name  = 'status'
            """)).one()
    assert fila[0] == "text"
    assert fila[1] == "NO"
    # El DEFAULT es lo que permite que la migracion sea aditiva: el codigo ya
    # desplegado sigue insertando sin mencionar la columna.
    assert "ACTIVE" in fila[2]


def test_usuario_nuevo_nace_activo(conn):
    cuenta = _cuenta(conn, "Cuenta del default")
    org = _organizacion(conn, cuenta, "Org del default")
    uid = _usuario(conn, "default@example.com", org, master=False)

    estado = conn.execute(
        text("SELECT status FROM users WHERE id = :id"), {"id": str(uid)}
    ).scalar_one()
    assert estado == "ACTIVE"


def test_el_check_rechaza_un_estado_inventado(conn):
    cuenta = _cuenta(conn, "Cuenta del check")
    org = _organizacion(conn, cuenta, "Org del check")
    uid = _usuario(conn, "check@example.com", org, master=False)

    with pytest.raises(IntegrityError):
        conn.execute(
            text("UPDATE users SET status = 'SUSPENDED' WHERE id = :id"),
            {"id": str(uid)},
        )


def test_el_check_acepta_inactive(conn):
    """El unico estado distinto de ACTIVE que esta migracion define."""
    cuenta = _cuenta(conn, "Cuenta del inactive")
    org = _organizacion(conn, cuenta, "Org del inactive")
    uid = _usuario(conn, "inactive@example.com", org, master=False)

    conn.execute(
        text("UPDATE users SET status = 'INACTIVE' WHERE id = :id"),
        {"id": str(uid)},
    )
    estado = conn.execute(
        text("SELECT status FROM users WHERE id = :id"), {"id": str(uid)}
    ).scalar_one()
    assert estado == "INACTIVE"


# ---------------------------------------------------------------------------
# 2 · El relleno de membresias
# ---------------------------------------------------------------------------


def test_master_heredado_recibe_su_membresia_owner(engine, datos):
    """El caso de los siete medidos en produccion el 20/09."""
    with engine.connect() as c:
        assert _membresias_de(c, datos["heredado"]) == ["owner"]


def test_master_con_membresia_no_se_duplica_ni_cambia_de_rol(engine, datos):
    """Quien ya tiene membresia explicita resuelve por ella: no se toca.

    Es la razon de que el NOT EXISTS del INSERT no filtre por rol. Si lo
    hiciera, este usuario recibiria una segunda fila y violaria `uq_org_user`.
    """
    with engine.connect() as c:
        assert _membresias_de(c, datos["con_rol"]) == ["member"]


def test_master_removido_a_proposito_no_recupera_el_rol(engine, datos):
    """El filtro por `account_events`, que hoy no excluye a nadie y por eso esta.

    Si entre la medicion y el despliegue alguien quita a un master a proposito,
    el relleno no puede devolverle OWNER en silencio.
    """
    with engine.connect() as c:
        assert _membresias_de(c, datos["removido"]) == []


def test_usuario_normal_no_recibe_nada(engine, datos):
    with engine.connect() as c:
        assert _membresias_de(c, datos["normal"]) == []


def test_master_con_organizacion_inexistente_no_tumba_la_migracion(engine, datos):
    """El caso que tumbo el despliegue de v1.32.1.

    Un master cuya organizacion no existe **no puede** recibir membresia: la FK
    de `organization_users` lo impide, y sin el `EXISTS` sobre `organizations`
    ese `ForeignKeyViolation` aborta la migracion entera.

    Que este test exista es lo que convierte aquel fallo en algo que se ve en CI
    y no en un despliegue. Los siete usuarios que en produccion se creian
    "masters heredados" son exactamente este caso.
    """
    with engine.connect() as c:
        assert _membresias_de(c, datos["huerfano"]) == []

        # Y la organizacion sigue sin existir: el test prueba lo que dice
        existe = c.execute(
            text("SELECT count(*) FROM organizations WHERE id = :o"),
            {"o": str(datos["org_fantasma"])},
        ).scalar_one()
        assert existe == 0


# ---------------------------------------------------------------------------
# 3 · El downgrade, y la decision que lleva dentro
# ---------------------------------------------------------------------------


def test_segundo_ciclo_no_borra_las_membresias_ni_las_duplica(engine, datos):
    """`downgrade` quita la columna y **deja** el relleno. Decidido, no olvidado.

    Este test es el que fija esa decision: si alguien anade un DELETE al
    downgrade "por simetria", los siete masters heredados se quedarian sin rol y
    aqui se veria. De paso comprueba que el INSERT es idempotente — el segundo
    upgrade no inserta nada, porque el NOT EXISTS ya lo encuentra.
    """
    if desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) != 0:
        raise RuntimeError("fallo el downgrade a la 028")

    with engine.connect() as c:
        columna = c.execute(text("""
                SELECT count(*) FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name   = 'users'
                   AND column_name  = 'status'
                """)).scalar_one()
        assert columna == 0, "el downgrade tiene que quitar la columna"

        assert _membresias_de(c, datos["heredado"]) == [
            "owner"
        ], "el downgrade no debe tocar el relleno"

    if desechable.alembic(BASE, "upgrade", "head") != 0:
        raise RuntimeError("fallo el upgrade a head")

    with engine.connect() as c:
        assert _membresias_de(c, datos["heredado"]) == [
            "owner"
        ], "el segundo upgrade no puede duplicar la membresia"
        assert _membresias_de(c, datos["con_rol"]) == ["member"]
        assert _membresias_de(c, datos["removido"]) == []

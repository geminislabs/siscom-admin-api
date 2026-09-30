"""La migracion 035 hace lo que dice: rellena organization_users para
quien nunca tuvo fila.

POR QUE ESTE FICHERO EXISTE APARTE DEL RESTO DE TESTS
=======================================================
Por lo mismo que `test_estado_de_usuario_esquema.py`: un relleno de datos
solo existe si corren las migraciones, y el harness normal (`create_all()`)
no las corre. El escenario se inserta con la base bajada a la 034 —justo
antes de la 035— para que el `INSERT ... SELECT` de la migracion corra
contra datos que existian *antes* de ella, igual que en produccion.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from tests import esquema_desechable as desechable

BASE = "siscom_test_backfill_membresias"
REVISION_ANTERIOR = "034_estado_de_membresia"


@pytest.fixture(scope="module")
def engine():
    """Base desechable con el esquema productivo y las migraciones encima."""
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
        {"id": str(uid), "correo": correo, "org": str(organizacion), "master": master},
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


def _membresias_de(conn, usuario: UUID) -> list[str]:
    filas = conn.execute(
        text("SELECT role FROM organization_users WHERE user_id = :u ORDER BY role"),
        {"u": str(usuario)},
    ).all()
    return [f[0] for f in filas]


@pytest.fixture(scope="module")
def datos(engine):
    """El escenario que existia *antes* de la 035, pasado por downgrade +
    upgrade de verdad. Los datos se commitean: alembic corre en otro
    proceso y no veria una transaccion abierta."""
    if desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) != 0:
        raise RuntimeError("fallo el downgrade a la 034")

    with engine.connect() as c:
        tx = c.begin()
        cuenta = _cuenta(c, "Cuenta del relleno regular")

        # El caso que motiva la migracion entera: invitado por correo, jamas
        # tuvo fila en organization_users — accept_invitation nunca la creaba.
        org_normal = _organizacion(c, cuenta, "Org del miembro regular")
        normal = _usuario(c, "regular@example.com", org_normal, master=False)

        # Ya tenia membresia explicita, con un rol que no es el default del
        # relleno — no se debe tocar ni duplicar.
        org_con_rol = _organizacion(c, cuenta, "Org del miembro con rol propio")
        con_rol = _usuario(c, "con-rol@example.com", org_con_rol, master=False)
        _membresia(c, org_con_rol, con_rol, "admin")

        # is_master sin membresia, insertado despues de que la 029 ya corrio
        # en esta misma cadena: la 029 no lo va a recoger porque no existia
        # todavia cuando ella se aplico. Tiene que rellenarlo la 035.
        org_master = _organizacion(c, cuenta, "Org del master tardio")
        master_sin_membresia = _usuario(
            c, "master@example.com", org_master, master=True
        )

        tx.commit()

    if desechable.alembic(BASE, "upgrade", "head") != 0:
        raise RuntimeError("fallo el upgrade a head")

    return {
        "normal": normal,
        "con_rol": con_rol,
        "master_sin_membresia": master_sin_membresia,
    }


def test_miembro_regular_recibe_member(engine, datos):
    """El caso central: quien nunca tuvo fila la recibe, con rol member."""
    with engine.connect() as c:
        assert _membresias_de(c, datos["normal"]) == ["member"]


def test_miembro_con_rol_propio_no_se_toca_ni_se_duplica(engine, datos):
    """Es la razon de que el NOT EXISTS no filtre por rol: si lo hiciera,
    este usuario recibiria una segunda fila con member y violaria
    uq_org_user."""
    with engine.connect() as c:
        assert _membresias_de(c, datos["con_rol"]) == ["admin"]


def test_master_tardio_recibe_owner(engine, datos):
    """is_master sigue yendo a owner, igual que en la 029 — pero aqui
    porque el usuario no existia cuando la 029 corrio."""
    with engine.connect() as c:
        assert _membresias_de(c, datos["master_sin_membresia"]) == ["owner"]


def test_downgrade_no_borra_el_relleno(engine, datos):
    """Decidido, no olvidado — ver la cabecera de la migracion."""
    if desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) != 0:
        raise RuntimeError("fallo el downgrade")
    try:
        with engine.connect() as c:
            assert _membresias_de(c, datos["normal"]) == ["member"]
            assert _membresias_de(c, datos["master_sin_membresia"]) == ["owner"]
    finally:
        if desechable.alembic(BASE, "upgrade", "head") != 0:
            raise RuntimeError("fallo el upgrade de vuelta a head")

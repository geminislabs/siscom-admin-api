"""La migracion 037 hace lo que dice: a quien tiene la organizacion por
defecto apuntando a una membresia no activa, y alguna otra activa, se la
mueve a la activa mas antigua.

Aparte del resto de tests por lo mismo que
`test_backfill_membresias_regulares_esquema.py`: un relleno de datos solo
existe si corren las migraciones, y el harness normal (`create_all()`) no las
corre. El escenario se inserta con la base bajada a la 036 —justo antes de la
037— para que el `UPDATE` corra contra datos que existian antes de ella.
"""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from app.utils.datetime import utcnow
from tests import esquema_desechable as desechable

BASE = "siscom_test_por_defecto_activa"
REVISION_ANTERIOR = "036_organizacion_por_defecto"


@pytest.fixture(scope="module")
def engine():
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


def _organizacion(conn, cuenta: UUID, nombre: str) -> UUID:
    oid = uuid4()
    conn.execute(
        text(
            "INSERT INTO organizations (id, account_id, name) "
            "VALUES (:id, :cuenta, :nombre)"
        ),
        {"id": str(oid), "cuenta": str(cuenta), "nombre": nombre},
    )
    return oid


def _usuario(conn, correo: str, por_defecto: UUID) -> UUID:
    uid = uuid4()
    conn.execute(
        text(
            "INSERT INTO users (id, email, default_organization_id, is_master, "
            "external_id) VALUES (:id, :correo, :org, false, :correo)"
        ),
        {"id": str(uid), "correo": correo, "org": str(por_defecto)},
    )
    return uid


def _membresia(conn, org: UUID, usuario: UUID, estado: str, dias: int) -> None:
    conn.execute(
        text(
            "INSERT INTO organization_users "
            "(id, organization_id, user_id, role, status, created_at) "
            "VALUES (:id, :org, :usuario, 'member', :estado, :creada)"
        ),
        {
            "id": str(uuid4()),
            "org": str(org),
            "usuario": str(usuario),
            "estado": estado,
            "creada": utcnow() - timedelta(days=dias),
        },
    )


def _por_defecto(conn, usuario: UUID) -> UUID:
    return conn.execute(
        text("SELECT default_organization_id FROM users WHERE id = :u"),
        {"u": str(usuario)},
    ).scalar_one()


@pytest.fixture(scope="module")
def datos(engine):
    """Datos commiteados: alembic corre en otro proceso y no veria una
    transaccion abierta."""
    if desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) != 0:
        raise RuntimeError("fallo el downgrade a la 036")

    with engine.connect() as c:
        tx = c.begin()
        cuenta = uuid4()
        c.execute(
            text("INSERT INTO accounts (id, account_name) VALUES (:id, 'Relleno')"),
            {"id": str(cuenta)},
        )
        pausada = _organizacion(c, cuenta, "Pausada")
        antigua = _organizacion(c, cuenta, "Antigua")
        reciente = _organizacion(c, cuenta, "Reciente")

        # El caso que motiva la migracion: por defecto pausada, dos activas.
        rota = _usuario(c, "rota@example.com", pausada)
        _membresia(c, pausada, rota, "INACTIVE", dias=90)
        _membresia(c, reciente, rota, "ACTIVE", dias=1)
        _membresia(c, antigua, rota, "ACTIVE", dias=30)

        # Por defecto valida: no se toca aunque haya otra mas antigua.
        valida = _usuario(c, "valida@example.com", reciente)
        _membresia(c, reciente, valida, "ACTIVE", dias=1)
        _membresia(c, antigua, valida, "ACTIVE", dias=30)

        # Sin ninguna activa: la columna se queda (es NOT NULL).
        sin_salida = _usuario(c, "sin-salida@example.com", pausada)
        _membresia(c, pausada, sin_salida, "INACTIVE", dias=10)

        # Por defecto sin fila alguna en organization_users, y otra activa.
        sin_fila = _usuario(c, "sin-fila@example.com", pausada)
        _membresia(c, antigua, sin_fila, "ACTIVE", dias=5)

        tx.commit()

    if desechable.alembic(BASE, "upgrade", "head") != 0:
        raise RuntimeError("fallo el upgrade a head")

    return {
        "rota": rota,
        "valida": valida,
        "sin_salida": sin_salida,
        "sin_fila": sin_fila,
        "pausada": pausada,
        "antigua": antigua,
        "reciente": reciente,
    }


def test_por_defecto_pausada_pasa_a_la_activa_mas_antigua(engine, datos):
    with engine.connect() as c:
        assert _por_defecto(c, datos["rota"]) == datos["antigua"]


def test_por_defecto_valida_no_se_toca(engine, datos):
    with engine.connect() as c:
        assert _por_defecto(c, datos["valida"]) == datos["reciente"]


def test_sin_ninguna_activa_la_columna_se_queda(engine, datos):
    with engine.connect() as c:
        assert _por_defecto(c, datos["sin_salida"]) == datos["pausada"]


def test_por_defecto_sin_membresia_tambien_se_repara(engine, datos):
    with engine.connect() as c:
        assert _por_defecto(c, datos["sin_fila"]) == datos["antigua"]


def test_downgrade_no_deshace_la_reparacion(engine, datos):
    """Decidido, no olvidado — ver la cabecera de la migracion."""
    if desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) != 0:
        raise RuntimeError("fallo el downgrade")
    try:
        with engine.connect() as c:
            assert _por_defecto(c, datos["rota"]) == datos["antigua"]
    finally:
        if desechable.alembic(BASE, "upgrade", "head") != 0:
            raise RuntimeError("fallo el upgrade de vuelta a head")

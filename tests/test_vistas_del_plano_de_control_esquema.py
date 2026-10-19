"""La `044` crea las vistas `control_plane.*` sobre el esquema real.

Va como test de esquema por la misma razón que la `043`: el harness normal
construye la base con `create_all()` y crea las vistas copiando el SQL de la
migración, así que allí funcionarían aunque la migración no corriera sobre lo
que hay en producción.

Lo que de verdad protege es `test_cada_vista_tiene_las_columnas_del_contrato`:
si una migración futura renombra una columna que una vista expone —lo que hizo
la `036` con `users.organization_id`—, la vista deja de crearse o cambia de
columnas, y esto falla en la CI de admin-api y no en el arranque de otro
servicio (ADR-008 §4b).
"""

import pytest
from sqlalchemy import create_engine, text

from app.services.messaging.control_plane import ENTIDADES, ESQUEMA
from tests import esquema_desechable as desechable

BASE = "siscom_test_vistas_del_plano_de_control"
REVISION_ANTERIOR = "043_defaults_de_id"


@pytest.fixture(scope="module")
def engine():
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


def _columnas(engine, vista):
    with engine.connect() as c:
        return tuple(
            c.execute(
                text("""
                    SELECT column_name FROM information_schema.columns
                     WHERE table_schema = :e AND table_name = :v
                     ORDER BY ordinal_position
                """),
                {"e": ESQUEMA, "v": vista},
            ).scalars()
        )


@pytest.mark.parametrize("entidad", sorted(ENTIDADES))
def test_cada_vista_tiene_las_columnas_del_contrato(engine, entidad):
    definicion = ENTIDADES[entidad]
    assert _columnas(engine, definicion.vista) == definicion.columnas


def test_las_vistas_se_pueden_leer(engine):
    """Que existan no basta: una vista con un JOIN roto existe y falla al leerla."""
    with engine.connect() as c:
        for definicion in ENTIDADES.values():
            c.execute(text(f"SELECT * FROM {ESQUEMA}.{definicion.vista} LIMIT 1"))


def test_downgrade_borra_el_esquema_y_upgrade_lo_vuelve_a_crear(engine):
    assert desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) == 0
    with engine.connect() as c:
        existe = c.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :e"),
            {"e": ESQUEMA},
        ).scalar()
    assert existe is None

    assert desechable.alembic(BASE, "upgrade", "head") == 0
    assert _columnas(engine, ENTIDADES["user"].vista) == ENTIDADES["user"].columnas

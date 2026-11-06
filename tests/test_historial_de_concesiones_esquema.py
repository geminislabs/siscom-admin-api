"""La migración 046 hace lo que dice, sobre el esquema productivo.

Lo que prueba no lo construye bien `create_all()`: el trigger que archiva las
concesiones sólo existe en la migración (el harness normal lo copia de ella,
pero eso no prueba que la migración lo cree). Y el relleno —las concesiones
de antes quedan con `include_history = true`— sólo se ve haciendo el viaje
`downgrade` → insertar → `upgrade`.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text

from tests import esquema_desechable as desechable

BASE = "siscom_test_historial_concesiones"
REVISION_ANTERIOR = "045_user_devices_locale"


@pytest.fixture(scope="module")
def engine():
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


def _escenario(c) -> dict:
    cuenta = uuid4()
    c.execute(
        text("INSERT INTO accounts (id, account_name) VALUES (:id, 'Cuenta')"),
        {"id": str(cuenta)},
    )
    org = uuid4()
    c.execute(
        text(
            "INSERT INTO organizations (id, account_id, name) VALUES (:id, :c, 'Org')"
        ),
        {"id": str(org), "c": str(cuenta)},
    )
    usuario = uuid4()
    correo = f"{usuario.hex[:8]}@example.com"
    c.execute(
        text("""
            INSERT INTO users (id, email, default_organization_id, external_id)
            VALUES (:id, :correo, :org, :correo)
            """),
        {"id": str(usuario), "correo": correo, "org": str(org)},
    )
    unidad = uuid4()
    c.execute(
        text("""
            INSERT INTO public.units (id, name, unit_ref, organization_id)
            VALUES (:id, 'Unidad', :ref, :org)
            """),
        {"id": str(unidad), "ref": str(uuid4()), "org": str(org)},
    )
    c.execute(
        text("INSERT INTO user_units (user_id, unit_id) VALUES (:u, :un)"),
        {"u": str(usuario), "un": str(unidad)},
    )
    return {"usuario": usuario, "unidad": unidad}


@pytest.fixture(scope="module")
def previa(engine):
    """Una concesión creada **antes** de la 046, pasada por el upgrade real."""
    if desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) != 0:
        raise RuntimeError("falló el downgrade a la 045")
    with engine.begin() as c:
        datos = _escenario(c)
    if desechable.alembic(BASE, "upgrade", "head") != 0:
        raise RuntimeError("falló el upgrade a head")
    return datos


def _include_history(c, usuario: UUID, unidad: UUID):
    return c.execute(
        text(
            "SELECT include_history FROM user_units WHERE user_id = :u AND unit_id = :un"
        ),
        {"u": str(usuario), "un": str(unidad)},
    ).scalar_one()


def test_las_concesiones_de_antes_conservan_su_historico(engine, previa):
    """Acotarlas al desplegar le quitaría a alguien algo que nadie decidió quitarle."""
    with engine.connect() as c:
        assert _include_history(c, previa["usuario"], previa["unidad"]) is True


def test_una_concesion_nueva_nace_acotada(engine):
    with engine.connect() as c:
        tx = c.begin()
        try:
            datos = _escenario(c)
            assert _include_history(c, datos["usuario"], datos["unidad"]) is False
        finally:
            tx.rollback()


def test_borrar_una_concesion_la_archiva_con_su_ventana(engine):
    with engine.connect() as c:
        tx = c.begin()
        try:
            datos = _escenario(c)
            c.execute(
                text("DELETE FROM user_units WHERE user_id = :u"),
                {"u": str(datos["usuario"])},
            )
            fila = c.execute(
                text("""
                    SELECT unit_id, granted_at, revoked_at, include_history
                      FROM user_unit_grants_history WHERE user_id = :u
                    """),
                {"u": str(datos["usuario"])},
            ).one()
        finally:
            tx.rollback()

    assert fila.unit_id == datos["unidad"]
    assert fila.granted_at is not None
    assert fila.revoked_at >= fila.granted_at
    assert fila.include_history is False


def test_la_cascada_de_una_unidad_borrada_tambien_archiva(engine):
    """Sin claves foráneas en el historial, el trigger no choca con la cascada."""
    with engine.connect() as c:
        tx = c.begin()
        try:
            datos = _escenario(c)
            c.execute(
                text("DELETE FROM public.units WHERE id = :id"),
                {"id": str(datos["unidad"])},
            )
            archivadas = c.execute(
                text(
                    "SELECT count(*) FROM user_unit_grants_history WHERE unit_id = :un"
                ),
                {"un": str(datos["unidad"])},
            ).scalar_one()
        finally:
            tx.rollback()

    assert archivadas == 1


def test_la_vista_del_plano_de_control_no_cambia(engine):
    """alert-distributor lee `control_plane.user_units`: su contrato sigue igual."""
    with engine.connect() as c:
        columnas = [r[0] for r in c.execute(text("""
                SELECT column_name FROM information_schema.columns
                 WHERE table_schema = 'control_plane' AND table_name = 'user_units'
                 ORDER BY ordinal_position
                """))]
    assert columnas == ["organization_id", "user_id", "unit_id", "role"]

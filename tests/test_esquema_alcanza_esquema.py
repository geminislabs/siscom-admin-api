"""La `033`: la limpieza acotada, y que cada restriccion entra como toca.

Lo que hay que probar aqui no es que las columnas queden NOT NULL —eso lo dice
el comparador de deriva, y mejor que un test— sino las dos decisiones que la
migracion toma sobre **datos**:

  1. Borra 45 filas de configuracion inalcanzable, y **se planta** si en vez de
     45 se encuentra con miles.
  2. Distingue las dos FKs sucias de las limpias: `trips` entra `NOT VALID`
     porque su historial no se tira, el resto entra validado.
"""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests import esquema_desechable as desechable

BASE = "siscom_test_alcanza"
REVISION_ANTERIOR = "032_alert_rules_created_by"


@pytest.fixture(scope="module")
def engine():
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


def _capability(conn):
    cid = uuid4()
    conn.execute(
        text(
            "INSERT INTO public.capabilities (id, code, description, value_type)"
            " VALUES (:i, :c, 'Prueba', 'int')"
        ),
        {"i": cid, "c": f"cap_{cid.hex[:8]}"},
    )
    return cid


def _huerfanas(conn, cuantas):
    """Filas de plan_capabilities colgando de un plan que no existe."""
    cap = _capability(conn)
    for _ in range(cuantas):
        conn.execute(
            text(
                "INSERT INTO public.plan_capabilities"
                " (id, plan_id, capability_id, value_int)"
                " VALUES (:i, :p, :c, 1)"
            ),
            {"i": uuid4(), "p": uuid4(), "c": cap},
        )


def test_borra_la_configuracion_inalcanzable(engine):
    assert desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) == 0

    with engine.begin() as c:
        _huerfanas(c, 45)

    assert desechable.alembic(BASE, "upgrade", "head") == 0

    with engine.connect() as c:
        quedan = c.execute(text("""
                SELECT count(*) FROM public.plan_capabilities pc
                 WHERE NOT EXISTS (SELECT 1 FROM public.plans p
                                    WHERE p.id = pc.plan_id)
                """)).scalar_one()

    assert quedan == 0


def test_se_planta_si_la_limpieza_es_mucho_mayor_de_lo_medido(engine):
    """El techo, probado por el unico camino que lo prueba: pasandolo.

    Cuarenta y cinco filas muertas son una limpieza. Miles serian otra cosa, y
    no una que deba decidir una migracion sin que nadie la mire.
    """
    assert desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) == 0

    with engine.begin() as c:
        _huerfanas(c, 201)

    assert (
        desechable.alembic(BASE, "upgrade", "head") != 0
    ), "la migracion deberia haberse plantado"

    # Y se planta sin borrar nada: las 201 siguen ahi.
    with engine.connect() as c:
        siguen = c.execute(text("""
                SELECT count(*) FROM public.plan_capabilities pc
                 WHERE NOT EXISTS (SELECT 1 FROM public.plans p
                                    WHERE p.id = pc.plan_id)
                """)).scalar_one()
    assert siguen == 201

    with engine.begin() as c:
        c.execute(text("""
                DELETE FROM public.plan_capabilities pc
                 WHERE NOT EXISTS (SELECT 1 FROM public.plans p
                                    WHERE p.id = pc.plan_id)
                """))
    assert desechable.alembic(BASE, "upgrade", "head") == 0


def test_trips_entra_sin_validar_y_el_resto_validado(engine):
    """La diferencia la decide el dato, no la costumbre."""
    with engine.connect() as c:
        estado = dict(c.execute(text("""
                    SELECT conname, convalidated FROM pg_constraint
                     WHERE conname IN ('trips_device_id_fkey',
                                       'subscriptions_plan_id_fkey',
                                       'orders_organization_id_fkey')
                    """)).all())

    assert estado["trips_device_id_fkey"] is False
    assert estado["subscriptions_plan_id_fkey"] is True
    assert estado["orders_organization_id_fkey"] is True


def test_una_suscripcion_no_puede_apuntar_a_un_plan_inexistente(engine):
    """Lo que compran las FKs validadas, dicho en una operacion."""
    with engine.connect() as c:
        tx = c.begin()
        try:
            with pytest.raises(IntegrityError):
                c.execute(
                    text(
                        "INSERT INTO public.subscriptions (id, organization_id, plan_id)"
                        " VALUES (:i, :o, :p)"
                    ),
                    {"i": uuid4(), "o": uuid4(), "p": uuid4()},
                )
        finally:
            tx.rollback()

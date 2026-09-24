"""La `032` deja borrar a quien creo una regla de alerta.

No prueba el esquema, prueba **la consecuencia**: antes de esta migracion,
`alert_rules.created_by` era `NOT NULL` y su propia clave foranea era
`ON DELETE SET NULL`. Las dos cosas juntas significan que borrar al autor de
una regla **falla**, y el error no menciona `alert_rules` por ningun lado.

Se escribe como test de esquema —y no en el harness normal— porque el escenario
necesita la tabla real con su FK, que `create_all()` construye desde unos
modelos que ya no coinciden con la base.
"""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests import esquema_desechable as desechable

BASE = "siscom_test_autor_de_reglas"
REVISION_ANTERIOR = "031_fk_organizacion_unidad"


@pytest.fixture(scope="module")
def engine():
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


def _escenario(conn):
    """Una regla de alerta con su autor, colgando de una organizacion real."""
    cuenta, org, usuario, regla = uuid4(), uuid4(), uuid4(), uuid4()
    conn.execute(
        text("INSERT INTO public.accounts (id, account_name) VALUES (:id, 'Cuenta')"),
        {"id": cuenta},
    )
    conn.execute(
        text(
            "INSERT INTO public.organizations (id, name, account_id)"
            " VALUES (:id, 'Org', :cuenta)"
        ),
        {"id": org, "cuenta": cuenta},
    )
    conn.execute(
        text(
            "INSERT INTO public.users (id, email, organization_id)"
            " VALUES (:id, :correo, :org)"
        ),
        {"id": usuario, "correo": f"{usuario}@example.com", "org": org},
    )
    conn.execute(
        text("""
            INSERT INTO public.alert_rules
                   (id, organization_id, created_by, name, type, config, fingerprint)
            VALUES (:id, :org, :autor, 'Regla', 'velocidad', '{}'::jsonb, :huella)
            """),
        {"id": regla, "org": org, "autor": usuario, "huella": str(regla)},
    )
    return {"organizacion": org, "usuario": usuario, "regla": regla}


def test_borrar_al_autor_deja_la_regla_sin_autor(engine):
    """Lo que la migracion compra, dicho como lo viviria alguien."""
    with engine.begin() as c:
        datos = _escenario(c)

    with engine.begin() as c:
        c.execute(
            text("DELETE FROM public.users WHERE id = :id"), {"id": datos["usuario"]}
        )

    with engine.connect() as c:
        autor = c.execute(
            text("SELECT created_by FROM public.alert_rules WHERE id = :id"),
            {"id": datos["regla"]},
        ).scalar_one()

    # La regla sobrevive a la baja de quien la creo, perdiendo la autoria. Esa
    # es la semantica que pedia el `ON DELETE SET NULL` y que el `NOT NULL`
    # impedia.
    assert autor is None

    with engine.begin() as c:
        c.execute(
            text("DELETE FROM public.organizations WHERE id = :id"),
            {"id": datos["organizacion"]},
        )


def test_antes_de_la_032_el_borrado_del_autor_fallaba(engine):
    """El test que fija por que existe la migracion.

    Sin bajar a la revision anterior, este fichero no probaria que la `032`
    arregla algo: probaria que una columna nullable admite NULL, que es una
    tautologia.
    """
    # Comprobado, no supuesto: si el downgrade falla, la base se queda en head
    # y el test pasaria "verde" probando exactamente nada.
    assert (
        desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) == 0
    ), "fallo el downgrade a la 031"

    try:
        with engine.begin() as c:
            datos = _escenario(c)

        with pytest.raises(IntegrityError):
            with engine.begin() as c:
                c.execute(
                    text("DELETE FROM public.users WHERE id = :id"),
                    {"id": datos["usuario"]},
                )

        # Y lo que NO falla, que conviene fijar porque es contraintuitivo y
        # porque yo lo di por sentado al reves: borrar la organizacion funciona
        # incluso con el NOT NULL puesto. `alert_rules` tambien cascadea desde
        # `organizations`, asi que las reglas se van con ella y no queda
        # ninguna fila a la que poner NULL.
        with engine.begin() as c:
            c.execute(
                text("DELETE FROM public.organizations WHERE id = :id"),
                {"id": datos["organizacion"]},
            )

        with engine.connect() as c:
            vivas = c.execute(
                text("SELECT count(*) FROM public.alert_rules WHERE id = :id"),
                {"id": datos["regla"]},
            ).scalar_one()
        assert vivas == 0
    finally:
        assert desechable.alembic(BASE, "upgrade", "head") == 0

"""La FK de units.organization_id, la otra mitad del predicado de aislamiento

Revision ID: 031_fk_organizacion_unidad
Revises: 030_fk_organizacion_usuario
Create Date: 2026-09-24 00:00:00.000000

QUE VIENE A CERRAR
==================
La misma forma del hueco que cerro la `030`, en la otra mitad de la pareja. El
aislamiento entre organizaciones se escribe a mano en mas de veinte endpoints
como:

    Unit.organization_id == current_user.organization_id

Los dos lados de esa comparacion son columnas que el modelo declara `NOT NULL`
con `ForeignKey("organizations.id", ondelete="CASCADE")`. La `030` puso la de
`users`. Esta pone la de `units`, que hasta hoy admitia una unidad apuntando a
una organizacion inexistente — o a ninguna.

Lo hizo visible el comparador de deriva en cuanto aprendio a mirar
restricciones (#110): era una de las nueve claves foraneas que el modelo
declaraba y la base no tenia.

LOS DATOS, MEDIDOS CONTRA PRODUCCION ANTES DE ESCRIBIR ESTO
===========================================================
    sin_valor  apuntan_al_vacio  total
            0                 0     26

**Cero y cero**, asi que esta migracion es mas simple que la `030`: no hace
falta `NOT VALID`. La restriccion entra **validada**, verificando las 26 filas
existentes, y no queda deuda anotada detras.

Que sea posible hoy no lo hace permanente: si la medicion sale distinta en otro
entorno, el paso 1 lo dice y aborta antes de tocar nada.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "031_fk_organizacion_unidad"
down_revision: Union[str, None] = "030_fk_organizacion_usuario"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT = "units_organization_id_fkey"


def upgrade() -> None:
    # Misma leccion que la 029 y la 030. `units` no se lee en cada peticion
    # autenticada como `users`, pero si en el listado del mapa, que es la
    # pantalla que todo el mundo tiene abierta.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("SET LOCAL statement_timeout = '5min'")

    conn = op.get_bind()

    sin_valor = conn.execute(
        sa.text("SELECT count(*) FROM public.units WHERE organization_id IS NULL")
    ).scalar_one()

    apuntan_al_vacio = conn.execute(
        sa.text(
            """
            SELECT count(*)
              FROM public.units u
             WHERE u.organization_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM public.organizations o
                                WHERE o.id = u.organization_id)
            """
        )
    ).scalar_one()

    print(
        f"🔎 units.organization_id: {sin_valor} sin valor, "
        f"{apuntan_al_vacio} apuntando a una organizacion inexistente"
    )

    # A diferencia de la `030`, aqui no se acepta seguir con filas rotas. Se
    # midio cero y cero, asi que cualquier otra cosa es una sorpresa — y una
    # sorpresa sobre la columna que decide quien ve que unidad se mira antes de
    # tocarla, no despues.
    if sin_valor or apuntan_al_vacio:
        raise RuntimeError(
            f"units.organization_id: {sin_valor} sin valor y {apuntan_al_vacio} "
            "apuntando a una organizacion inexistente. La medicion del 24/09 dio "
            "cero y cero, asi que esto no estaba previsto: hay que mirar esas "
            "filas antes de poner la restriccion. Consulta:\n"
            "  SELECT id, unit_ref, organization_id FROM units u\n"
            "   WHERE organization_id IS NULL\n"
            "      OR NOT EXISTS (SELECT 1 FROM organizations o\n"
            "                      WHERE o.id = u.organization_id);"
        )

    op.execute("ALTER TABLE public.units ALTER COLUMN organization_id SET NOT NULL")

    # Sin `NOT VALID`: no hay nada que perdonar, asi que se verifica ahora y la
    # restriccion nace valida. Con 26 filas la verificacion es instantanea.
    op.execute(
        f"""
        ALTER TABLE public.units
          ADD CONSTRAINT {CONSTRAINT}
          FOREIGN KEY (organization_id)
          REFERENCES public.organizations (id)
          ON DELETE CASCADE
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"ALTER TABLE public.units DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute("ALTER TABLE public.units ALTER COLUMN organization_id DROP NOT NULL")

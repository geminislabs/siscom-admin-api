"""Historial de concesiones de unidades: `user_units` con versiones

Revision ID: 046_historial_de_concesiones
Revises: 045_user_devices_locale
Create Date: 2026-11-06 00:00:00.000000

POR QUE
=======
Retirar una unidad a un usuario borraba la fila de `user_units` y con ella el
dato de cuándo tuvo acceso. Sin ese dato, `access_control.accessible_refs` no
podía acotar el histórico: a quien se le concedía una unidad hoy veía todo su
pasado, incluidos los recorridos de quien la manejaba antes.

La regla nueva (decidida por Jesús el 06/11/2026): **una concesión da acceso a
lo ocurrido mientras estuvo vigente**, salvo que quien la concede marque
explícitamente `include_history`.

COMO
====
Es el patrón de tabla con versiones del sistema (`temporal_tables`, SQL:2011):

- `user_units` sigue siendo **las concesiones vigentes**. Ninguna de sus
  lecturas cambia —ni las doce del API ni la vista `control_plane.user_units`
  que lee alert-distributor—, así que ninguna puede olvidarse de filtrar.
- `user_unit_grants_history` guarda cada concesión retirada con su ventana
  `[granted_at, revoked_at)`. La llena un trigger `AFTER DELETE`, así que la
  cubre cualquier camino que borre, con o sin ORM, también las cascadas.
- Sin claves foráneas a propósito: un borrado en cascada de la unidad dispara
  el trigger y la fila de historial apuntaría a la unidad que se está borrando.

QUE HACE
========
1. `user_units.include_history BOOLEAN NOT NULL DEFAULT false`.
2. Las concesiones que ya existen quedan con `include_history = true`: siguen
   viendo lo que veían. Sólo las nuevas nacen acotadas.
3. Crea `user_unit_grants_history` y el trigger.

ROLLBACK
========
`downgrade` borra la tabla de historial (y lo que haya acumulado), el trigger y
la columna. Seguro justo después de liberar; después, lo que se pierde es el
historial de concesiones retiradas, que antes de esta migración no existía.
Requiere ser dueño de `public.user_units` (ver la memoria de `ALTER TABLE`).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "046_historial_de_concesiones"
down_revision: Union[str, None] = "045_user_devices_locale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def sentencias() -> list[str]:
    """La tabla de historial, la función y el trigger.

    Lo reutiliza `tests/conftest.py`: `create_all()` crea la tabla desde el
    modelo pero no la función ni el trigger.
    """
    return [
        """
        CREATE TABLE IF NOT EXISTS public.user_unit_grants_history (
            id uuid DEFAULT gen_random_uuid() NOT NULL,
            user_id uuid NOT NULL,
            unit_id uuid NOT NULL,
            granted_by uuid NULL,
            granted_at timestamptz NULL,
            revoked_at timestamptz DEFAULT now() NOT NULL,
            role text NOT NULL,
            include_history boolean NOT NULL,
            CONSTRAINT user_unit_grants_history_pkey PRIMARY KEY (id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_user_unit_grants_history_user_unit
            ON public.user_unit_grants_history USING btree (user_id, unit_id)
        """,
        """
        CREATE OR REPLACE FUNCTION public.archivar_concesion_retirada()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO public.user_unit_grants_history
                (user_id, unit_id, granted_by, granted_at, revoked_at, role,
                 include_history)
            VALUES
                (OLD.user_id, OLD.unit_id, OLD.granted_by, OLD.granted_at, now(),
                 OLD.role, OLD.include_history);
            RETURN OLD;
        END;
        $$
        """,
        "DROP TRIGGER IF EXISTS trg_archivar_concesion_retirada ON public.user_units",
        """
        CREATE TRIGGER trg_archivar_concesion_retirada
            AFTER DELETE ON public.user_units
            FOR EACH ROW EXECUTE FUNCTION public.archivar_concesion_retirada()
        """,
    ]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        ALTER TABLE public.user_units
        ADD COLUMN IF NOT EXISTS include_history BOOLEAN NOT NULL DEFAULT false
        """
    )
    # Las concesiones de antes de esta migración veían todo el histórico, y
    # siguen viéndolo: acotarlas sería quitarle a alguien, al desplegar, algo
    # que nadie decidió quitarle.
    op.execute("UPDATE public.user_units SET include_history = true")
    for sql in sentencias():
        op.execute(sql)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_archivar_concesion_retirada ON public.user_units"
    )
    op.execute("DROP FUNCTION IF EXISTS public.archivar_concesion_retirada()")
    op.execute("DROP TABLE IF EXISTS public.user_unit_grants_history")
    op.execute("ALTER TABLE public.user_units DROP COLUMN IF EXISTS include_history")

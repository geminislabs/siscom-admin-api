"""alert_rules.created_by deja de ser NOT NULL, porque su propia FK exige NULL

Revision ID: 032_alert_rules_created_by
Revises: 031_fk_organizacion_unidad
Create Date: 2026-09-24 00:00:00.000000

LA CONTRADICCION
================
Produccion declara estas dos cosas sobre la misma columna:

    created_by uuid NOT NULL,
    CONSTRAINT fk_alert_rules_user FOREIGN KEY (created_by)
        REFERENCES public.users(id) ON DELETE SET NULL

No pueden cumplirse a la vez. Al borrar un usuario, Postgres intenta poner
`created_by = NULL` como pide la FK, y el `NOT NULL` lo rechaza: **el DELETE
falla**. La regla de alerta no se queda huerfana — lo que no se puede es borrar
al usuario.

El modelo ya tenia razon, y lo decia por escrito:

    # ON DELETE SET NULL en DDL requiere nullable=True.
    created_by: Optional[UUID] = ...

CUANDO FALLA, MEDIDO Y NO DEDUCIDO
==================================
La primera version de esta nota decia que la `030` habia hecho la cadena
alcanzable: borrar una organizacion cascadea a sus usuarios, y cada uno chocaria
con este NOT NULL. **Se probo y es falso.** Borrar la organizacion funciona,
porque `alert_rules` tambien tiene `ON DELETE CASCADE` desde `organizations`:
las reglas se van con ella y no queda ninguna fila a la que poner NULL.

Lo que si falla, reproducido:

    DELETE FROM users WHERE id = <autor de una regla viva>
    -> ERROR: null value in column "created_by" violates not-null constraint

Es decir: **borrar un usuario directamente**, cuando alguna regla suya sobrevive
a la operacion. Hoy ningun endpoint borra filas de `users` —dar de baja escribe
`status`, y quitar a alguien de una organizacion borra la membresia—, asi que no
esta vivo. Es una trampa puesta para quien lo haga a mano, y para el dia que
exista una baja de verdad: el mensaje de error no menciona `alert_rules` por
ningun lado.

QUE NO SE HACE, Y POR QUE
=========================
No se cambia la FK a CASCADE ni a RESTRICT. `SET NULL` es la semantica correcta:
la regla de alerta sobrevive a la baja de quien la creo, perdiendo la autoria.
Cambiarla seria decidir que las reglas se borran con su autor — otra cosa, y no
una que esta migracion deba decidir.

Tampoco toca ninguna fila: hoy todas tienen autor, y el endpoint que las crea
(`alert_rules.py:253`) lo pone siempre.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "032_alert_rules_created_by"
down_revision: Union[str, None] = "031_fk_organizacion_unidad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        "ALTER TABLE public.alert_rules ALTER COLUMN created_by DROP NOT NULL"
    )


def downgrade() -> None:
    # Volver a ponerlo restaura la contradiccion, asi que solo puede hacerse si
    # ninguna fila se quedo sin autor entretanto. Si alguna lo hizo, este
    # downgrade falla — y es lo correcto: revertir no puede inventarse un autor.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        "ALTER TABLE public.alert_rules ALTER COLUMN created_by SET NOT NULL"
    )

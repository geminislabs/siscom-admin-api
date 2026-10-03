"""Renombra users.organization_id a default_organization_id

Revision ID: 036_organizacion_por_defecto
Revises: 035_backfill_membresias
Create Date: 2026-10-02 00:00:00.000000

QUE ES Y QUE NO ES
===================
Solo un rename de columna. Sin ALTER de tipo, sin tocar NOT NULL ni la FK:
`ALTER TABLE ... RENAME COLUMN` es un cambio de catalogo en Postgres, no
reescribe la tabla ni bloquea lectores. El indice `idx_users_organization_master`
y la FK `users_organization_id_fkey` siguen intactos — Postgres los sigue
resolviendo por OID de columna, no por nombre, asi que no hace falta tocarlos.

POR QUE
========
Es la mitad de esquema del "selector de cuenta" (B3, §26 del documento de
arquitectura). Hoy `users.organization_id` es la UNICA fuente de autorizacion
en unas 64 lecturas (`current_user.organization_id`) repartidas por todo
`app/api/v1/endpoints/`, y la membresia real vive en `organization_users` sin
que nadie la consulte para decidir "en que organizacion actua esta sesion".

Renombrar la columna a `default_organization_id` y declarar `organization_id`
como propiedad de Python (resuelta contra una membresia activa elegida en la
sesion, con la columna de respaldo) permite que esas 64 lecturas seleccionen
la organizacion activa sin tocarse una por una: siguen leyendo
`current_user.organization_id`, y es la propiedad la que decide cual es.

Medido antes de escribir esto: hoy CERO usuarios tienen mas de una membresia
activa en produccion (16 membresias activas en total, ninguna duplicada por
usuario) — el selector es pura infraestructura, inerte por diseno, igual que
el resto de B3.

QUE NO HACE
============
No mueve datos ni cambia el valor de la columna para ninguna fila. No decide
donde vive la organizacion activa de la sesion (eso es `app/api/deps.py`, no
el esquema). No toca `organization_users.organization_id`, que es una columna
distinta en una tabla distinta.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "036_organizacion_por_defecto"
down_revision: Union[str, None] = "035_backfill_membresias"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "organization_id",
        new_column_name="default_organization_id",
        schema="public",
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "default_organization_id",
        new_column_name="organization_id",
        schema="public",
    )

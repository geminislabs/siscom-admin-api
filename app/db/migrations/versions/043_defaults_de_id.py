"""account_events.id y organization_capabilities.id generan su id

Revision ID: 043_defaults_de_id
Revises: 042_marca_de_la_invitacion
Create Date: 2026-10-13 00:00:00.000000

QUE CIERRA
==========
En producción las dos columnas son `uuid NOT NULL` **sin DEFAULT**, y los
modelos las declaran con `server_default gen_random_uuid()`: el código inserta
sin id y cuenta con que la base lo ponga. Resultado, un 500 con
`NotNullViolation` en cada inserción.

- `account_events`: todo endpoint que audita. Lo destapó GAC al convertir una
  cuenta en marca (13/10/2026), pero también caían publicar la marca, guardar
  una capability de cuenta y alta, rol, estado y baja de miembros de una
  organización. La tabla estaba vacía: nunca se había podido escribir en ella.
- `organization_capabilities`: crear un override. Esa escritura está cerrada
  con 403 desde la `041`, por eso nadie lo vio.

Los tests no lo veían porque su base sale de los modelos. `verificar-deriva.py`
compara desde este PR también los defaults del servidor, y con el snapshot de
producción más las migraciones encuentra exactamente estas dos columnas.

QUE HACE
========
`ALTER COLUMN id SET DEFAULT gen_random_uuid()`. Solo cambia el catálogo: no
reescribe ni recorre la tabla. Las dos son de `pgadmin`, que `siscom_migrator`
ya alteró en la `033` y la `042`.

ROLLBACK
========
`downgrade()` quita los defaults y deja las columnas como estaban. El código
anterior también cuenta con ellos, así que revertir la imagen sin bajar la
migración es lo correcto: bajarla solo hace falta para desplegar un tag
anterior a la `042`.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "043_defaults_de_id"
down_revision: Union[str, None] = "042_marca_de_la_invitacion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLAS = ("account_events", "organization_capabilities")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for tabla in TABLAS:
        op.execute(
            f"ALTER TABLE public.{tabla} ALTER COLUMN id SET DEFAULT gen_random_uuid()"
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for tabla in TABLAS:
        op.execute(f"ALTER TABLE public.{tabla} ALTER COLUMN id DROP DEFAULT")

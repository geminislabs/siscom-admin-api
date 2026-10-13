"""La invitación guarda la marca de quien invita

Revision ID: 042_marca_de_la_invitacion
Revises: 041_overrides_sin_autoservicio
Create Date: 2026-10-13 00:00:00.000000

QUE CIERRA
==========
Las tres consultas por correo que quedaban sin acotar por marca (§26: 5 de 8
cerradas en v1.48.0-v1.48.1) están en el flujo de invitación
(`app/api/v1/endpoints/users.py`): invitar, reenviar y aceptar buscaban
`User.email == :correo` en **todas** las marcas. Y había un fallo hermano: el
correo de invitación ya salía con la marca de quien invita, pero
`accept_invitation` creaba al usuario con `brand_account_id` NULL (la marca por
defecto). Con un partner, el invitado de Mero Mero recibiría un enlace a
`meromero.com` y no podría entrar ahí, porque el login busca
`(brand_account_id, email)`.

La marca del invitado es la de quien invita: es la que ya pinta el correo. Para
que `accept_invitation` la conozca —es anónimo, solo trae el token— tiene que
viajar en el token.

QUE HACE
========
`tokens_confirmacion.brand_account_id uuid NULL`, con FK a `accounts`. NULL es
la marca por defecto, igual que en `users`: todas las invitaciones pendientes de
hoy son de la marca por defecto y siguen funcionando sin relleno.

`ON DELETE CASCADE`: una invitación de una marca que ya no existe no tiene a
dónde llevar a nadie, y dejarla con NULL la convertiría en silencio en una
invitación de Geminis.

Agregar una columna nullable sin default no reescribe la tabla; la FK sí
recorre las filas para validarse, y la tabla es chica. `lock_timeout` por si
algo la tiene tomada. **Requiere que `siscom_migrator` sea dueño de la tabla**
(no existe `GRANT ALTER`); ver la nota de la release.

ROLLBACK
========
`downgrade()` borra la columna. El código anterior no la lee, así que basta
revertir la imagen; bajar a la `041` solo hace falta para desplegar un tag
anterior, y pierde la marca de las invitaciones pendientes de otras marcas (hoy
no hay ninguna).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "042_marca_de_la_invitacion"
down_revision: Union[str, None] = "041_overrides_sin_autoservicio"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        ALTER TABLE public.tokens_confirmacion
          ADD COLUMN brand_account_id uuid NULL
          REFERENCES public.accounts(id) ON DELETE CASCADE
        """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("ALTER TABLE public.tokens_confirmacion DROP COLUMN brand_account_id")

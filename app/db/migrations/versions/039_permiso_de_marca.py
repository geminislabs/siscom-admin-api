"""El permiso branding.write para el owner y el admin de la cuenta (B4)

Revision ID: 039_permiso_de_marca
Revises: 038_catalogo_de_permisos
Create Date: 2026-10-12 00:00:00.000000

Solo datos: una fila en `permissions` y dos en `role_permissions`. Llega en el
mismo PR que los endpoints de marca (`app/api/v1/endpoints/branding.py`), que
son los únicos que lo exigen: la regla de la `038` es que un permiso entra con
su endpoint, y `tests/test_permisos_esquema.py` falla si uno llega sin el otro.

Owner y admin, no billing ni member: es lo que D4 fijó para B4 el 11/10/2026.

ROLLBACK
========
`downgrade()` borra el permiso; `ON DELETE CASCADE` se lleva sus dos filas de
`role_permissions`. Con el código anterior —sin los endpoints— la fila no se
lee, así que basta revertir la imagen; bajar a la `038` solo hace falta para
desplegar un tag anterior.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "039_permiso_de_marca"
down_revision: Union[str, None] = "038_catalogo_de_permisos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO public.permissions (code, description, scope)
        VALUES ('branding.write',
                'Editar, publicar y descartar la marca de la cuenta',
                'account')
        """)
    op.execute("""
        INSERT INTO public.role_permissions (role_id, permission_code, scope)
        SELECT r.id, 'branding.write', 'account'
          FROM public.roles r
         WHERE r.scope = 'account'
           AND r.account_id IS NULL
           AND r.code IN ('owner', 'admin')
        """)


def downgrade() -> None:
    op.execute("DELETE FROM public.permissions WHERE code = 'branding.write'")

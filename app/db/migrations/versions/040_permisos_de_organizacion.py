"""Los permisos operativos que hoy decidía la jerarquía de roles (D6 de B4)

Revision ID: 040_permisos_de_organizacion
Revises: 039_permiso_de_marca
Create Date: 2026-10-13 00:00:00.000000

QUE ES
======
Solo datos: ocho filas en `permissions` y las de `role_permissions` que les
tocan a los roles de sistema de alcance `organization` (sembrados por la 038).
Llega en el mismo PR que `require_organization_permission`
(`app/api/deps.py`) y los quince endpoints que pasan de
`require_organization_role(...)` a pedir permiso; `tests/test_permisos_esquema.py`
falla si un permiso llega sin endpoint o al revés.

EL REPARTO NO CAMBIA NADA
=========================
Cada permiso lo reciben exactamente los roles que la jerarquía de
`require_organization_role` dejaba pasar en esos endpoints:

  - `"member"`            -> owner, admin, billing, member
  - `"admin"`             -> owner, admin
  - `"owner"`             -> owner
  - `"owner", "billing"`  -> owner, admin, billing   (admin incluía billing)

Lo que cambia es dónde vive la regla: en la base en vez de en el código, para
que un rol personalizado sea una fila y no un cambio en quince endpoints.
`tests/test_permisos_de_organizacion.py` compara rol por rol el reparto con la
jerarquía vieja.

Todos van con alcance `organization`, también los que por D6 son comerciales
(`accounts.write`, `subscriptions.manage`): pasarlos a `account` cambiaría qué
membresía se consulta (`account_users` en vez de `organization_users`), y eso
es una decisión, no una migración. Queda anotado en el PR.

ROLLBACK
========
`downgrade()` borra los ocho permisos; `ON DELETE CASCADE` se lleva sus filas
de `role_permissions`. El código anterior no los lee, así que basta revertir
la imagen; bajar a la `039` solo hace falta para desplegar un tag anterior. Al
revés no: esta imagen con la base en la `039` da 403 en los quince endpoints
(falla cerrado), por eso la migración corre antes de arrancar la imagen nueva.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "040_permisos_de_organizacion"
down_revision: Union[str, None] = "039_permiso_de_marca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TODOS = ("owner", "admin", "billing", "member")

# (código, descripción, roles de sistema que lo reciben)
PERMISOS = (
    ("organizations.read", "Ver las organizaciones y su detalle", _TODOS),
    ("organizations.write", "Crear organizaciones y editar sus datos", ("owner",)),
    ("organization_users.read", "Ver los miembros de la organización", _TODOS),
    (
        "organization_users.manage",
        "Agregar y quitar miembros, cambiar su rol y su estado",
        ("owner", "admin"),
    ),
    ("capabilities.read", "Ver las capabilities de la organización", _TODOS),
    (
        "capabilities.override",
        "Crear y borrar overrides de capabilities de la organización",
        ("owner",),
    ),
    ("accounts.write", "Editar los datos de la cuenta", ("owner",)),
    (
        "subscriptions.manage",
        "Cancelar suscripciones y cambiar su renovación automática",
        ("owner", "admin", "billing"),
    ),
)


def sentencias() -> list[str]:
    """El SQL de la siembra. `tests/conftest.py` lo reutiliza tal cual."""
    salida = []
    for code, descripcion, roles in PERMISOS:
        desc = descripcion.replace("'", "''")
        lista = ", ".join(f"'{r}'" for r in roles)
        salida.append(
            "INSERT INTO public.permissions (code, description, scope) "
            f"VALUES ('{code}', '{desc}', 'organization')"
        )
        salida.append(
            "INSERT INTO public.role_permissions (role_id, permission_code, scope) "
            f"SELECT r.id, '{code}', 'organization' FROM public.roles r "
            "WHERE r.scope = 'organization' AND r.account_id IS NULL "
            f"AND r.code IN ({lista})"
        )
    return salida


def upgrade() -> None:
    for sql in sentencias():
        op.execute(sql)


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _, _ in PERMISOS)
    op.execute(f"DELETE FROM public.permissions WHERE code IN ({codes})")

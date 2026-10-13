"""El owner de una organización ya no puede crear overrides de capabilities

Revision ID: 041_overrides_sin_autoservicio
Revises: 040_permisos_de_organizacion
Create Date: 2026-10-13 00:00:00.000000

QUE CIERRA
==========
`POST/DELETE /organizations/{id}/capabilities` dejaba al owner de una
organización escribir overrides de capabilities **de su propia organización**,
y el override tiene la prioridad más alta en la resolución
(`organization_override ?? plan_capability ?? default`). Quien se registra queda
como owner de la organización que crea, así que cualquiera con una cuenta podía
subirse los límites de su plan (`max_devices`, `max_geofences`, `history_days`)
llamando a la API a mano. Ningún cliente usa esas rutas.

Un override es una decisión comercial —lleva `reason` y `expires_at`— y le toca
a Geminis, no a quien lo disfruta. Es el mismo principio que el techo
descendente de §4: nadie se regala capacidad.

QUE HACE
========
Solo datos: quita la fila de `role_permissions` que daba
`capabilities.override` al owner de organización. El permiso sigue en el
catálogo y las rutas lo siguen exigiendo, así que responden 403 a todos. El
día que GAC necesite escribir overrides lo hará por una ruta interna con
PASETO, como las capabilities de cuenta (`/internal/accounts/{id}/capabilities`).

Los overrides que ya existan se quedan como están: siguen aplicando hasta que
venzan. Antes de liberar conviene contarlos en producción.

ROLLBACK
========
`downgrade()` le devuelve el permiso al owner. Revertir solo la imagen no lo
devuelve: el código anterior también lee el catálogo desde la 040.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "041_overrides_sin_autoservicio"
down_revision: Union[str, None] = "040_permisos_de_organizacion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (permiso, roles de organización que lo pierden)
RETIRADOS = (("capabilities.override", ("owner",)),)


def _filtro(code: str, roles: tuple[str, ...]) -> str:
    lista = ", ".join(f"'{r}'" for r in roles)
    return (
        f"permission_code = '{code}' AND role_id IN ("
        "SELECT id FROM public.roles WHERE scope = 'organization' "
        f"AND account_id IS NULL AND code IN ({lista}))"
    )


def sentencias() -> list[str]:
    """El SQL del cambio. `tests/conftest.py` lo reutiliza tal cual."""
    return [
        f"DELETE FROM public.role_permissions WHERE {_filtro(code, roles)}"
        for code, roles in RETIRADOS
    ]


def upgrade() -> None:
    for sql in sentencias():
        op.execute(sql)


def downgrade() -> None:
    for code, roles in RETIRADOS:
        lista = ", ".join(f"'{r}'" for r in roles)
        op.execute(
            "INSERT INTO public.role_permissions (role_id, permission_code, scope) "
            f"SELECT r.id, '{code}', 'organization' FROM public.roles r "
            "WHERE r.scope = 'organization' AND r.account_id IS NULL "
            f"AND r.code IN ({lista})"
        )

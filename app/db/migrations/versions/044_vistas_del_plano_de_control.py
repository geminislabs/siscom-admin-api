"""Vistas control_plane.*: la foto de arranque de los consumidores de eventos

Revision ID: 044_vistas_del_plano_de_control
Revises: 043_defaults_de_id
Create Date: 2026-10-19 00:00:00.000000

QUE CIERRA
==========
`alert-distributor` y `event-processor` arrancan leyendo directamente las
tablas de esta API. La `036` renombró `users.organization_id` y la consulta de
permisos del distribuidor dejó de funcionar ese mismo día. Nadie lo vio
durante diecisiete días, porque el contenedor no se reinició; el siguiente
arranque habría dejado a todos sin alertas (corregido en `alert-distributor`
`v0.2.0`, 19/10/2026). Ningún test de este repo podía verlo: lo que leen los
consumidores no estaba escrito en ningún lado.

QUE HACE
========
Crea el esquema `control_plane` con una vista por entidad del contrato
(`docs/architecture/eventos-de-control.md`, ADR-008 §4b). Cada vista tiene
exactamente las columnas del `data` de su evento, y los eventos se construyen
leyendo de ellas (`app/services/messaging/control_plane.py`): la foto y el
evento no pueden divergir.

Las vistas se ejecutan con los privilegios de su dueño, así que quien las lee
solo necesita `USAGE` sobre el esquema y `SELECT` sobre las vistas, no acceso a
las tablas. La migración se los da al usuario de runtime de esta API
(`DB_USER`), que lee las vistas después de cada commit para construir los
eventos. `alert-distributor` y `event-processor` se conectan como `siscom`
(medido el 19/10/2026): si ese es también el `DB_USER` de esta API, no hace
falta ningún otro `GRANT`. Un consumidor con otro usuario lo pide aparte
(sección «Operación» del contrato).

Antes de crear nada comprueba que el usuario que migra puede crear esquemas, y
si no, aborta diciéndolo. Mismo motivo que la comprobación de dueños de la
`033`: el permiso de quien ejecuta no aparece en ningún test, porque en la base
desechable somos superusuario.

ROLLBACK
========
`downgrade()` borra el esquema con sus vistas. No hay datos: solo definiciones.
Revertir la imagen sin bajar la migración es lo normal, porque nada del código
anterior lee las vistas. Bajarla solo hace falta para desplegar un tag anterior
a la `043`, y deja sin foto a cualquier consumidor que ya las use.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

from app.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "044_vistas_del_plano_de_control"
down_revision: Union[str, None] = "043_defaults_de_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ESQUEMA = "control_plane"

# Una vista por entidad del contrato, con las columnas de su `data`, en orden.
# Van en plural, como las tablas: `user` es palabra reservada y obligaría a
# cada consumidor a escribir `control_plane."user"`.
# `tests/test_vistas_del_plano_de_control_esquema.py` compara estas columnas con
# las de la base migrada, y `app/services/messaging/control_plane.py` construye
# los eventos leyendo de aquí.
VISTAS: dict[str, str] = {
    "users": """
        SELECT u.id, u.status
          FROM public.users u
    """,
    "organization_users": """
        SELECT ou.organization_id, ou.user_id, ou.role, ou.status
          FROM public.organization_users ou
    """,
    "user_units": """
        SELECT un.organization_id, uu.user_id, uu.unit_id, uu.role
          FROM public.user_units uu
          JOIN public.units un ON un.id = uu.unit_id
         WHERE un.deleted_at IS NULL
    """,
    # La asignación vigente por equipo, con el mismo desempate que usa
    # event-processor (la más reciente, NULLS LAST). Un equipo sin asignación
    # vigente no aparece: su evento es DELETE.
    "unit_devices": """
        SELECT DISTINCT ON (ud.device_id)
               ud.device_id, ud.unit_id, un.organization_id
          FROM public.unit_devices ud
          JOIN public.units un ON un.id = ud.unit_id
         WHERE ud.unassigned_at IS NULL
           AND un.deleted_at IS NULL
         ORDER BY ud.device_id, ud.assigned_at DESC NULLS LAST
    """,
    "user_devices": """
        SELECT d.id, d.user_id, d.device_token, d.platform, d.endpoint_arn,
               d.is_active, d.updated_at
          FROM public.user_devices d
    """,
}


def sentencias() -> list[str]:
    """El SQL de `upgrade()` sin la comprobación de permisos.

    Lo reutiliza `tests/conftest.py` para que el harness, que sale de
    `create_all()`, tenga las mismas vistas que producción.
    """
    resultado = [f"CREATE SCHEMA IF NOT EXISTS {ESQUEMA}"]
    for nombre, cuerpo in VISTAS.items():
        resultado.append(f"CREATE OR REPLACE VIEW {ESQUEMA}.{nombre} AS {cuerpo}")
    return resultado


def upgrade() -> None:
    puede = (
        op.get_bind()
        .execute(
            text(
                "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
            )
        )
        .scalar()
    )
    if not puede:
        raise RuntimeError(
            f"El usuario que migra no puede crear el esquema {ESQUEMA}. "
            "Concede `GRANT CREATE ON DATABASE <base> TO <usuario>` y vuelve a "
            "desplegar; no se ha tocado nada."
        )

    op.execute("SET LOCAL lock_timeout = '10s'")
    for sql in sentencias():
        op.execute(sql)

    # Si migra el mismo usuario que ejecuta (local, base desechable), ya es dueño.
    lector = settings.DB_USER
    existe = (
        op.get_bind()
        .execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r AND rolname <> current_user"),
            {"r": lector},
        )
        .scalar()
    )
    if existe:
        op.execute(f'GRANT USAGE ON SCHEMA {ESQUEMA} TO "{lector}"')
        op.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA {ESQUEMA} TO "{lector}"')


def downgrade() -> None:
    op.execute(f"DROP SCHEMA IF EXISTS {ESQUEMA} CASCADE")

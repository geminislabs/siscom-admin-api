"""Columna locale en public.user_devices y vista control_plane.user_devices

Revision ID: 045_user_devices_locale
Revises: 044_vistas_del_plano_de_control
Create Date: 2026-10-27 00:00:00.000000

QUE HACE
========
1. Añade `locale TEXT NOT NULL DEFAULT 'es'` a `public.user_devices` para que los
   clientes móviles (iOS y Android) persistan el idioma activo del dispositivo
   (`es` | `en`) al registrar el token de notificaciones push.
2. Recrea la vista `control_plane.user_devices` incluyendo `d.locale` para que
   `alert-distributor` reciba el idioma en la foto de arranque y en los eventos
   `UPSERT` de `control-plane-events`.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

from app.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "045_user_devices_locale"
down_revision: Union[str, None] = "044_vistas_del_plano_de_control"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ESQUEMA = "control_plane"


def sentencias() -> list[str]:
    """El SQL que actualiza la vista `control_plane.user_devices`.

    Se hace `DROP VIEW` + `CREATE VIEW` porque PostgreSQL no permite que
    `CREATE OR REPLACE VIEW` inserte `locale` antes de `updated_at`.
    Lo reutiliza `tests/conftest.py` después de ejecutar las sentencias de la 044.
    """
    return [
        f"DROP VIEW IF EXISTS {ESQUEMA}.user_devices",
        f"""
        CREATE VIEW {ESQUEMA}.user_devices AS
        SELECT d.id, d.user_id, d.device_token, d.platform, d.endpoint_arn,
               d.is_active, d.locale, d.updated_at
          FROM public.user_devices d
        """,
    ]


def _conceder_lectura_si_aplica() -> None:
    lector = settings.DB_USER
    existe = (
        op.get_bind()
        .execute(
            text(
                "SELECT 1 FROM pg_roles WHERE rolname = :r AND rolname <> current_user"
            ),
            {"r": lector},
        )
        .scalar()
    )
    if existe:
        op.execute(f'GRANT USAGE ON SCHEMA {ESQUEMA} TO "{lector}"')
        op.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA {ESQUEMA} TO "{lector}"')


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        ALTER TABLE public.user_devices
        ADD COLUMN IF NOT EXISTS locale TEXT NOT NULL DEFAULT 'es'
        """
    )
    for sql in sentencias():
        op.execute(sql)
    _conceder_lectura_si_aplica()


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"DROP VIEW IF EXISTS {ESQUEMA}.user_devices")
    op.execute(
        f"""
        CREATE VIEW {ESQUEMA}.user_devices AS
        SELECT d.id, d.user_id, d.device_token, d.platform, d.endpoint_arn,
               d.is_active, d.updated_at
          FROM public.user_devices d
        """
    )
    _conceder_lectura_si_aplica()
    op.execute("ALTER TABLE public.user_devices DROP COLUMN IF EXISTS locale")

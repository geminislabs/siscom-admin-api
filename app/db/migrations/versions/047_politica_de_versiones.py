"""Política de versiones de las apps móviles: public.client_version_policy

Revision ID: 047_politica_de_versiones
Revises: 046_historial_de_concesiones
Create Date: 2026-11-06 00:00:00.000000

POR QUE
=======
D2 del plan de data token y versiones: la versión mínima de cada app la decide
el servidor, no la app. Una fila por plataforma:

- `min_supported_version`: por debajo, actualización obligatoria. `NULL` = sin
  mínimo.
- `latest_version`: por debajo, aviso opcional. `NULL` = sin aviso.
- `blocked_versions`: versiones concretas rotas, bloqueadas aunque superen el
  mínimo.
- `store_url`: la ficha de la tienda a la que manda la app.

La lee `GET /api/v1/client-config` y, más adelante, el middleware 426. Hasta
que GAC la administre se cambia por SQL, poniendo a mano `updated_by`
(ver `docs/runbooks/politica-de-versiones.md`).

QUE HACE
========
Crea la tabla y siembra las dos plataformas **sin mínimo ni aviso**: al
desplegar no cambia nada para ningún cliente.

ROLLBACK
========
`downgrade` borra la tabla. Si ya se fijó un mínimo, se pierde: anotar los
valores antes (`SELECT * FROM public.client_version_policy`).
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

from app.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "047_politica_de_versiones"
down_revision: Union[str, None] = "046_historial_de_concesiones"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def sentencias() -> list[str]:
    """La tabla y la semilla. Lo reutiliza `tests/conftest.py` para la semilla."""
    return [
        """
        CREATE TABLE IF NOT EXISTS public.client_version_policy (
            platform text NOT NULL,
            min_supported_version text NULL,
            latest_version text NULL,
            blocked_versions text[] DEFAULT '{}'::text[] NOT NULL,
            store_url text NULL,
            updated_at timestamptz DEFAULT now() NOT NULL,
            updated_by text NULL,
            CONSTRAINT client_version_policy_pkey PRIMARY KEY (platform),
            CONSTRAINT ck_client_version_policy_platform
                CHECK (platform IN ('ios', 'android'))
        )
        """,
        """
        INSERT INTO public.client_version_policy (platform, updated_by)
        VALUES ('ios', 'migracion 047'), ('android', 'migracion 047')
        ON CONFLICT (platform) DO NOTHING
        """,
    ]


def _conceder_al_runtime() -> None:
    """Lectura y escritura para el runtime: ver `_conceder_al_runtime` en la 046."""
    runtime = settings.DB_USER
    existe = (
        op.get_bind()
        .execute(
            text(
                "SELECT 1 FROM pg_roles WHERE rolname = :r AND rolname <> current_user"
            ),
            {"r": runtime},
        )
        .scalar()
    )
    if existe:
        op.execute(
            "GRANT SELECT, INSERT, UPDATE ON public.client_version_policy "
            f'TO "{runtime}"'
        )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for sql in sentencias():
        op.execute(sql)
    _conceder_al_runtime()


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS public.client_version_policy")

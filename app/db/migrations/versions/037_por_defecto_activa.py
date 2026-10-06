"""La organizacion por defecto apunta a una membresia activa

Revision ID: 037_por_defecto_activa
Revises: 036_organizacion_por_defecto
Create Date: 2026-10-06 00:00:00.000000

QUE ES Y QUE NO ES
===================
Solo datos, ningun cambio de esquema. Es el relleno que acompana al
invariante que desde este mismo cambio sostiene
`OrganizationService.reparar_organizacion_por_defecto`: **si un usuario tiene
alguna membresia ACTIVE, su `default_organization_id` es una de ellas.**

EL HUECO QUE CIERRA
====================
Hasta este cambio, ni `PATCH /organizations/{org}/users/{id}/status` (pausar)
ni `DELETE /organizations/{org}/users/{id}` tocaban `default_organization_id`.
A quien le pausaban o quitaban la membresia por defecto le quedaba la columna
apuntando a una fila no activa, y `_load_current_user` (`app/api/deps.py`)
valida contra ella toda peticion sin `X-Organization-Id`: 403 en todo,
`/auth/organizations` incluido, aunque tuviera otras membresias activas. El
codigo ya no lo produce; esta migracion arregla a quien ya hubiera caido
antes del despliegue.

Medido el 02/10/2026: nadie tenia mas de una membresia activa en produccion,
asi que lo esperable es que no toque ninguna fila. Corre igual: la medida es
de hace dias y el `UPDATE` cuesta nada si no hay a quien aplicarlo.

POR QUE ESE CRITERIO
=====================
El mismo que el codigo, para que un usuario reparado aqui y uno reparado en
caliente terminen igual: la membresia activa mas antigua, con el id de la
organizacion como desempate porque `created_at` admite NULL.

A quien no le queda ninguna membresia activa no se le toca: la columna es NOT
NULL y el 403 es la respuesta correcta. Eso incluye a los siete huerfanos de
la `029`, cuya organizacion no existe y que no tienen membresia.

POR QUE EL DOWNGRADE NO DESHACE EL CAMBIO
==========================================
El valor anterior era justamente el roto —una organizacion en la que la
persona ya no es miembro activo—. Volver a ponerlo no devuelve nada que el
codigo anterior necesite: ese codigo lee la columna igual y simplemente
funciona mejor con un valor valido. Ademas no se guarda cual era.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "037_por_defecto_activa"
down_revision: Union[str, None] = "036_organizacion_por_defecto"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SET LOCAL statement_timeout = '5min'")

    op.execute("""
        UPDATE public.users u
           SET default_organization_id = elegida.organization_id
          FROM (
                SELECT DISTINCT ON (ou.user_id) ou.user_id, ou.organization_id
                  FROM public.organization_users ou
                 WHERE ou.status = 'ACTIVE'
                 ORDER BY ou.user_id,
                          ou.created_at ASC NULLS LAST,
                          ou.organization_id ASC
               ) elegida
         WHERE elegida.user_id = u.id
           AND NOT EXISTS (
                 SELECT 1
                   FROM public.organization_users actual
                  WHERE actual.user_id         = u.id
                    AND actual.organization_id = u.default_organization_id
                    AND actual.status          = 'ACTIVE')
        """)


def downgrade() -> None:
    # Ver la cabecera: el valor anterior era el roto y no se guarda. Alembic
    # exige un cuerpo real en downgrade() (test_migrations_chain.py) — este
    # SELECT no hace nada, existe solo para que el downgrade no finja
    # revertir una reparacion que deliberadamente se queda.
    op.execute("SELECT 1")

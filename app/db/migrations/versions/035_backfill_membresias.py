"""Backfill de organization_users para quien nunca tuvo fila

Revision ID: 035_backfill_membresias
Revises: 034_estado_de_membresia
Create Date: 2026-09-30 00:00:00.000000

QUE ES Y QUE NO ES
===================
Solo datos, ningun cambio de esquema. Es la mitad "backfill" del
expand/contract que cierra un hueco encontrado revisando el rediseno de
`DELETE /organizations/{org}/users/{user_id}`: `accept_invitation`
(`app/api/v1/endpoints/users.py`) nunca creo una fila en
`organization_users` al dar de alta a alguien invitado por correo — solo
escribia `users.organization_id`. La `029` solo relleno para `is_master`, y
dio cero filas contra produccion; nunca hubo relleno para miembros
regulares, que son la mayoria de las cuentas reales.

EL FALLO VIVO QUE VIENE A DESTRABAR
=====================================
`OrganizationService.get_user_role` es la unica fuente de verdad del rol
desde el 22/09/2026 — se borro el fallback a `is_master`. Sin fila en
`organization_users`, devuelve `None`, y `require_organization_role(...)`
—el guardian de todos los endpoints admin, incluido el nivel minimo
`"member"`— no deja pasar ningun rol: `ROLE_HIERARCHY.get(None, [])` es una
lista vacia. Cualquier persona invitada por correo de la forma clasica
recibe 403 en todo lo que pida rol. Se encontro por accidente, revisando un
problema distinto — no tiene relacion con el rediseno de `DELETE`, pero
esta migracion lo cierra de paso.

POR QUE EL ROL QUE SE ASIGNA
=============================
`invite_user` solo lo puede llamar un master (`is_master=True`), y la
persona invitada siempre nace `is_master=False` — el flujo clasico no tiene
seleccion de rol. El relleno correcto es `member` para todos los que no son
`is_master`, y `owner` para los que si — mismo criterio que la `029`, que ya
cubre ese caso (y da cero filas nuevas alli: esos usuarios o ya tienen
membresia, o son huerfanos que el filtro de abajo tambien excluye).

POR QUE LOS FILTROS
=====================
Mismo patron que la `029`, y por las mismas razones:

- `EXISTS` sobre `organizations` evita que la FK de `organization_users`
  aborte la migracion contra las filas huerfanas (`organization_id` que ya
  no existe — ver la `029` sobre los siete huerfanos, hoy `INACTIVE`).
- `NOT EXISTS` sobre la membresia, sin filtrar por rol: filtrar por rol
  podria insertar una segunda fila para alguien que ya tiene membresia con
  otro rol y violar `uq_org_user`.
- `NOT EXISTS` sobre `account_events` (`org_user_removed`): sin este filtro,
  a cualquiera que hubiera sacado `DELETE /organizations/{org}/users/{id}`
  antes de este despliegue el relleno le devolvia la membresia en silencio
  -exactamente lo que la 029 ya resolvia para masters, y que los tests de
  esa migracion (`test_master_removido_a_proposito_no_recupera_el_rol`)
  detectaron al correr junto con esta. No se acota por organization_id: el
  evento no dice a cual readmitir, asi que la postura segura es no
  rellenarle ninguna hasta que se le re-invite por la via normal -que desde
  este mismo cambio si crea la fila.

No se filtra por `users.status`: alguien `INACTIVE` no puede autenticarse
(Cognito deshabilitado), asi que el relleno no le da acceso a nadie — y si
se le reactiva despues, `accept_invitation` (corregido en el mismo cambio
que esta migracion) mantiene la fila al dia desde ese momento.

QUE NO HACE
============
No decide que pasa si alguien tiene de verdad mas de una organizacion —eso
es ortogonal—: esta migracion le da a cada usuario exactamente UNA
membresia explicita, la que ya tenia implicita en `users.organization_id`.
No introduce multi-org; solo hace explicito lo que ya era cierto.

No se guarda contra que dos `is_master` compartan `organization_id` y
ambos terminen `owner` de la misma organizacion — la `029` tampoco lo hizo,
y su medicion mostro que los unicos `is_master` sin membresia eran huerfanos
excluidos por el `EXISTS`. Se sigue el mismo criterio.

POR QUE EL DOWNGRADE NO DESHACE EL RELLENO
=============================================
Misma razon que la `029`: las filas que este paso crea no conceden nada que
`users.organization_id` no representara ya. Revertir esta migracion no es
motivo para quitarselas.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "035_backfill_membresias"
down_revision: Union[str, None] = "034_estado_de_membresia"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sin ALTER TABLE, asi que no hay riesgo de bloquear lectores de `users`
    # con ACCESS EXCLUSIVE como en la `029` — pero el INSERT...SELECT si
    # puede tardar si `users` crece, y un statement_timeout no cuesta nada.
    op.execute("SET LOCAL statement_timeout = '5min'")

    op.execute("""
        INSERT INTO public.organization_users (organization_id, user_id, role)
        SELECT u.organization_id, u.id,
               CASE WHEN u.is_master THEN 'owner' ELSE 'member' END
          FROM public.users u
         WHERE u.organization_id IS NOT NULL
           AND EXISTS (
                 SELECT 1
                   FROM public.organizations o
                  WHERE o.id = u.organization_id)
           AND NOT EXISTS (
                 SELECT 1
                   FROM public.organization_users ou
                  WHERE ou.user_id         = u.id
                    AND ou.organization_id = u.organization_id)
           AND NOT EXISTS (
                 SELECT 1
                   FROM public.account_events e
                  WHERE e.event_type = 'org_user_removed'
                    AND e.target_id  = u.id)
        """)


def downgrade() -> None:
    # Ver la cabecera: las filas de esta migracion no conceden nada que
    # users.organization_id no diera ya, asi que no se revierten. Alembic
    # exige un cuerpo real en downgrade() (test_migrations_chain.py) — este
    # SELECT no hace nada, existe solo para que el downgrade no finja
    # revertir un backfill que deliberadamente se queda.
    op.execute("SELECT 1")

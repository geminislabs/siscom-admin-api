"""Estado de la membresia: la columna que hace posible dar de baja sin borrar

Revision ID: 034_estado_de_membresia
Revises: 033_el_esquema_alcanza
Create Date: 2026-09-29 00:00:00.000000

QUE ES Y QUE NO ES
===================
Es **solo esquema**, igual que la 029: ningun modelo, endpoint ni servicio de
este repositorio lee todavia `organization_users.status`. Es la mitad
"expand" del expand/contract (§18) — la migracion viaja en un release y el
codigo que la usa (el endpoint de alta/baja, `UserOut` exponiendo el estado,
la accion en el panel) entra en rebanadas siguientes.

A diferencia de la 029, esta migracion no trae ningun relleno de datos: es
aditiva sobre una columna nueva con DEFAULT, y no hay ninguna fila que
reclasificar — nadie esta dado de baja hoy porque no existe la forma de
estarlo.

POR QUE `organization_users` Y NO `users`
==========================================
Decision cerrada el 28/09/2026 (ver documento de arquitectura §26): **la baja
es la membresia, no el usuario**. La `029` ya dejo una columna de estado en
`users`, pero esa resuelve otra pregunta — si la fila de credencial sigue
siendo valida — y ningun endpoint la usa para decidir acceso.

La pregunta que esta migracion responde es distinta: "¿esta persona activa
*en esta organizacion*?" Con una organizacion por persona hoy, las dos
preguntas dan la misma respuesta — pero el white-label va a traer
organizaciones con varios miembros y admins que solo alcanzan la suya. Si la
columna viviera en `users`, un admin de una organizacion podria desactivar a
alguien leyendo o escribiendo un estado que en realidad es global, y afecta a
las demas organizaciones a las que esa persona pertenezca. Ponerla en
`organization_users` hace que la baja sea, desde el primer dia, exactamente
lo que el white-label necesita: acotada a `(organization_id, user_id)`.

La palanca global (fraude, abuso, un usuario que hay que apagar en todas
partes a la vez) sigue sin existir y no es parte de esta migracion — queda
para cuando alguien la pida, igual que se decidio para `users.status`.

POR QUE CHECK Y NO ENUM
========================
Misma razon que la 027 y la 029: anadir un estado nuevo a un ENUM de
Postgres es una operacion con mas aristas que reescribir un CHECK, y aqui se
espera anadir estados (por ejemplo, uno para invitaciones pendientes que hoy
vive aparte) cuando esa pieza se disene.

POR QUE SOLO DOS VALORES
==========================
`ACTIVE` e `INACTIVE`, igual que `users.status`. Sembrar `SUSPENDED` o
`PENDING` ahora seria un valor sin significado acordado — exactamente lo que
la 027 y la 029 evitaron.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "034_estado_de_membresia"
down_revision: Union[str, None] = "033_el_esquema_alcanza"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ESTADOS = ("ACTIVE", "INACTIVE")


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. No colgarse esperando un bloqueo
    # ------------------------------------------------------------------
    # Misma leccion de la 029: `ALTER TABLE` pide ACCESS EXCLUSIVE, y
    # `organization_users` se lee en cada resolucion de rol
    # (`OrganizationService.get_user_role`), que corre en cada peticion
    # autenticada. Sin `lock_timeout`, un bloqueo ajeno convierte un cambio de
    # metadatos en autenticacion degradada durante el despliegue en vez de en
    # un fallo rapido y nombrado.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("SET LOCAL statement_timeout = '5min'")

    # ------------------------------------------------------------------
    # 1. La columna de estado
    # ------------------------------------------------------------------
    # NOT NULL con DEFAULT desde el principio: toda membresia existente nace
    # ACTIVE, que es lo que son hoy —no existe la baja todavia—, y el codigo
    # ya desplegado (add_member, invite_user) sigue insertando sin
    # mencionarla.
    op.execute("""
        ALTER TABLE public.organization_users
          ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'ACTIVE'
        """)

    op.execute("""
        ALTER TABLE public.organization_users
          DROP CONSTRAINT IF EXISTS ck_organization_users_status
        """)
    op.execute("""
        ALTER TABLE public.organization_users
          ADD CONSTRAINT ck_organization_users_status
          CHECK (status IN ('ACTIVE', 'INACTIVE'))
        """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE public.organization_users
          DROP CONSTRAINT IF EXISTS ck_organization_users_status
        """)
    op.execute("""
        ALTER TABLE public.organization_users
          DROP COLUMN IF EXISTS status
        """)

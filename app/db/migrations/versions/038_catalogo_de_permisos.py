"""El catalogo de permisos y los roles de sistema (D6 de B4)

Revision ID: 038_catalogo_de_permisos
Revises: 037_por_defecto_activa
Create Date: 2026-10-12 00:00:00.000000

QUE ES
======
Tres tablas nuevas y ocho filas. No toca ninguna tabla existente, asi que no
hay `ALTER TABLE` ni bloqueo sobre nada que este en uso.

  - `permissions`: el catalogo. Cada permiso tiene un `code` (`branding.write`),
    una descripcion y un alcance: `account` (lo comercial: marca, plan,
    facturacion) u `organization` (lo operativo: unidades, dispositivos).
  - `roles`: owner, admin, billing y member, una vez por alcance. Hoy solo
    existen los de sistema (`is_system`, sin `account_id`).
  - `role_permissions`: que permisos tiene cada rol.

POR QUE, SI LOS ROLES SIGUEN SIENDO FIJOS
=========================================
Jesus decidio el 12/10/2026 roles fijos ahora y roles personalizados a mediano
plazo. Lo que haria caro el cambio es que los endpoints pregunten por **nombre
de rol** (`require_organization_role("owner", "admin")`, 17 usos hoy). Si
preguntan por **permiso**, un rol personalizado es una fila en `roles` con
`account_id` y sus filas en `role_permissions`: ningun endpoint cambia.

Las membresias (`account_users.role`, `organization_users.role`) siguen
guardando el codigo del rol como texto. Pasar a `role_id` llega con los roles
personalizados, no antes.

EL CATALOGO NACE VACIO, A PROPOSITO
===================================
Un permiso solo significa algo si un endpoint lo verifica. Por eso cada permiso
entra en la misma migracion —y el mismo PR— que el endpoint que lo exige, y
`tests/test_permisos_esquema.py` falla si aparece un permiso que ningun
endpoint usa o un endpoint que exige uno que el catalogo no tiene. Aqui solo
van los roles, que si existen desde ya: son los mismos cuatro que hoy guardan
las membresias.

LO QUE LA BASE GARANTIZA SOLA
=============================
  - Un rol de alcance `account` no puede recibir un permiso de alcance
    `organization`, ni al reves: `role_permissions` lleva el alcance y dos FK
    compuestas lo atan al del rol y al del permiso. Sin esto, «owner de la
    organizacion puede editar la marca» seria una fila valida.
  - Rol de sistema si y solo si no tiene cuenta. Un rol personalizado siempre
    pertenece a una cuenta, y uno de sistema nunca.
  - Un solo rol de sistema por (alcance, codigo), y un solo rol por (cuenta,
    alcance, codigo).

Las FK simples (`role_id -> roles.id`, `permission_code -> permissions.code`)
conviven con las compuestas a proposito: son las que declara el modelo y las
que mira `scripts/verificar-deriva.py`, que compara columna por columna.

ROLLBACK
========
`downgrade()` borra las tres tablas. Nada fuera de ellas las referencia y el
codigo anterior no las lee, asi que volver a la imagen anterior y bajar a la
`037` deja todo como estaba.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "038_catalogo_de_permisos"
down_revision: Union[str, None] = "037_por_defecto_activa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Los mismos cuatro roles que hoy guardan `account_users.role` y
# `organization_users.role` (AccountRole y OrganizationRole).
_ROLES_DE_SISTEMA = (
    ("owner", "Propietario"),
    ("admin", "Administrador"),
    ("billing", "Facturación"),
    ("member", "Miembro"),
)


def upgrade() -> None:
    op.execute("""
        CREATE TABLE public.permissions (
          code        text PRIMARY KEY,
          description text NOT NULL,
          scope       text NOT NULL,
          created_at  timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_permissions_scope
            CHECK (scope IN ('account', 'organization')),
          -- recurso.accion en minusculas: `branding.write`, `units.delete`.
          CONSTRAINT ck_permissions_code_formato
            CHECK (code ~ '^[a-z][a-z_]*\\.[a-z][a-z_]*$'),
          -- Destino de la FK compuesta de role_permissions.
          CONSTRAINT uq_permissions_code_scope UNIQUE (code, scope)
        )
        """)

    op.execute("""
        CREATE TABLE public.roles (
          id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          scope      text NOT NULL,
          code       text NOT NULL,
          name       text NOT NULL,
          account_id uuid NULL
                     REFERENCES public.accounts(id) ON DELETE CASCADE,
          is_system  boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_roles_scope
            CHECK (scope IN ('account', 'organization')),
          CONSTRAINT ck_roles_sistema_sin_cuenta
            CHECK (is_system = (account_id IS NULL)),
          -- Destino de la FK compuesta de role_permissions.
          CONSTRAINT uq_roles_id_scope UNIQUE (id, scope)
        )
        """)
    op.execute("""
        CREATE UNIQUE INDEX uq_roles_de_sistema
          ON public.roles (scope, code)
          WHERE account_id IS NULL
        """)
    op.execute("""
        CREATE UNIQUE INDEX uq_roles_de_cuenta
          ON public.roles (account_id, scope, code)
          WHERE account_id IS NOT NULL
        """)

    op.execute("""
        CREATE TABLE public.role_permissions (
          role_id         uuid NOT NULL
                          REFERENCES public.roles(id) ON DELETE CASCADE,
          permission_code text NOT NULL
                          REFERENCES public.permissions(code) ON DELETE CASCADE,
          scope           text NOT NULL,
          created_at      timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (role_id, permission_code),
          CONSTRAINT fk_role_permissions_rol_mismo_alcance
            FOREIGN KEY (role_id, scope)
            REFERENCES public.roles (id, scope) ON DELETE CASCADE,
          CONSTRAINT fk_role_permissions_permiso_mismo_alcance
            FOREIGN KEY (permission_code, scope)
            REFERENCES public.permissions (code, scope) ON DELETE CASCADE
        )
        """)
    op.execute("""
        CREATE INDEX ix_role_permissions_permission_code
          ON public.role_permissions (permission_code)
        """)

    valores = ",\n".join(
        f"('{alcance}', '{code}', '{nombre}', true)"
        for alcance in ("account", "organization")
        for code, nombre in _ROLES_DE_SISTEMA
    )
    op.execute(f"""
        INSERT INTO public.roles (scope, code, name, is_system)
        VALUES {valores}
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.role_permissions")
    op.execute("DROP TABLE IF EXISTS public.roles")
    op.execute("DROP TABLE IF EXISTS public.permissions")

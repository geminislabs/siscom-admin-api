"""Identidad: external_id opaco, marca de la credencial y enrutamiento de proveedor

Revision ID: 028_identidad_esquema
Revises: 027_tenancy_esquema
Create Date: 2026-09-08 00:00:00.000000

Rebanada A de la Fase 3 (ver §5, §11 y §23 del documento de arquitectura).

QUE ES Y QUE NO ES
==================
Es **solo esquema**, igual que la 027. Ningun modelo, endpoint ni servicio de
este repositorio conoce todavia estas columnas: el codigo actual sigue creando
usuarios con el correo como username de Cognito, guardando el `sub` en
`cognito_sub` y buscando por `User.email` global. Esa es la mitad "expand" del
expand/contract (§18) — la migracion viaja en un release, y el codigo que la
usa en el siguiente.

Lo que hace posible que esta migracion sea aditiva de verdad es el trigger de
mas abajo: mientras el codigo viejo siga vivo, es el que rellena `external_id`
en cada alta. Sin el, los usuarios creados entre los dos releases nacerian sin
handle y la rebanada B tendria que salir a buscarlos.

LA PREMISA QUE ESTA MIGRACION DA POR CIERTA
===========================================
Que el username de Cognito de todo usuario existente **es su correo**. No es
una deduccion sobre lo que impone Cognito —esa fue la premisa falsa que costo
un mes, §5— sino sobre lo que hace esta aplicacion: los `admin_create_user` de
`auth.py` pasan el correo como `Username`. Aun asi es una afirmacion sobre
datos, y los datos pueden tener usuarios creados a mano desde la consola. El
runbook `docs/runbooks/desplegar-identidad.md` trae la consulta que lo
comprueba contra el pool **antes** de desplegar, y el UPDATE que corrige los
que no encajen. Correrla no es opcional.

QUE AÑADE
=========
  users.external_id        text NOT NULL — handle opaco ante el proveedor
  users.identity_provider  text NOT NULL DEFAULT 'cognito'
  users.brand_account_id   uuid NULL FK accounts — la marca de la credencial
  uq_users_marca_correo             UNIQUE (brand_account_id, email) parcial
  uq_users_correo_marca_por_defecto UNIQUE (email) parcial, marca NULL
  uq_users_proveedor_external_id    UNIQUE (identity_provider, external_id)
  users_identidad_before   trigger que rellena external_id mientras dure la ventana
  accounts.identity_provider text NULL — enrutamiento por cuenta (§5, regla 2)
  accounts.idp_config        jsonb NOT NULL DEFAULT '{}'

Y **quita** `users_email_key`, la unicidad global de correo. Es el unico cambio
no aditivo, y es el punto entero de la fase: dos personas distintas, una en
cada marca, pueden tener el mismo correo.

EL HANDLE Y EL SUJETO SON COSAS DISTINTAS
=========================================
`external_id` es **con que se autentica** (el `Username` de Cognito: correo
para los que ya existen, UUID para los que cree la rebanada B).
`cognito_sub` es **que sujeto afirma el token** (el `sub`, que es lo que
compara `deps.py` al verificar). En Cognito son dos identificadores distintos
del mismo usuario y ninguno se deduce del otro, asi que esta migracion no
renombra `cognito_sub` ni lo toca: se queda donde esta, y la rebanada B decide
si acaba llamandose `provider_subject` cuando exista un segundo proveedor.

Renombrarlo aqui habria sido gratis de escribir y caro de entender: dejaria una
columna llamada `external_id` guardando el `sub` y otra guardando el username,
que es justo la confusion que esta fase viene a deshacer.

POR QUE LA MARCA VA EN EL USUARIO Y ADMITE NULL
===============================================
`UNIQUE(brand_account_id, email)` (§5) exige tener la marca en la fila: es
derivable —organizacion -> cuenta -> raiz de su `account_path`— pero una
restriccion no puede depender de un JOIN.

`NULL` no significa "sin marca": significa **la marca por defecto**, la que se
sirve a cualquier `Host` que no resuelva a un `tenant_domains` verificado. Hoy
son todos los usuarios, porque no hay un solo dominio dado de alta. Y no se
rellena con la raiz de la cuenta de cada quien, que seria la traduccion
mecanica y estaria mal: eso los ataria a una marca que no existe y romperia su
login el dia que `/auth/login` empiece a filtrar por marca.

Que Geminis no tenga cuenta raiz es deliberado (§23): si todas las marcas
colgaran de una, `account_path @> ARRAY[esa]` casaria con el sistema entero.
El dia que la marca Geminis exista como cuenta con dominio propio, un UPDATE
de una linea convierte estos NULL en su id.

El precio del NULL es que la unicidad se parte en dos indices parciales, porque
en Postgres dos NULL nunca chocan. `NULLS NOT DISTINCT` haria lo mismo en un
solo objeto, pero exige Postgres 15 o mas y la version de produccion no esta
verificada desde aqui — que es exactamente el tipo de deduccion que §5 dice que
no se vuelve a hacer. Dos indices parciales funcionan en cualquier version y
dicen en su nombre lo que cubren.

REVERSIBILIDAD
==============
El `downgrade` restaura `users_email_key`, y por eso **puede fallar**: si para
entonces dos marcas ya comparten un correo, la unicidad global ya no es cierta
y no hay forma honesta de reponerla. La migracion lo detecta y aborta con el
recuento en el mensaje en vez de dejar la base a medias. Ver la seccion de
reversion del runbook.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "028_identidad_esquema"
down_revision: Union[str, None] = "027_tenancy_esquema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Los proveedores que el codigo sabe manejar hoy. Es uno solo, y el CHECK lo
# dice: ampliarlo es una migracion de una linea, mientras que un texto libre
# invita a que alguien escriba 'workos' en una fila meses antes de que exista
# el codigo que lo entienda — y a que el login de esa cuenta falle sin que
# nadie sepa por que.
_PROVEEDORES = ("cognito",)


def _existe_columna(conn, tabla: str, columna: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t "
                "AND column_name = :c"
            ),
            {"t": tabla, "c": columna},
        ).scalar()
    )


def _existe_restriccion(conn, nombre: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": nombre}
        ).scalar()
    )


def _restricciones_unicas_de_solo_correo(conn) -> list[str]:
    """Nombres de las restricciones UNIQUE que cubren `users(email)` y nada mas.

    Se busca por catalogo y no por nombre: `users_email_key` es el nombre que
    trae el esquema de produccion, pero una base restaurada o creada por
    `create_all()` puede haberla llamado de otra forma, y dejarse una viva
    convierte esta migracion en una que no hace nada visible.
    """
    filas = conn.execute(sa.text("""
            SELECT c.conname
              FROM pg_constraint c
              JOIN pg_class t ON t.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'public'
               AND t.relname = 'users'
               AND c.contype = 'u'
               AND (
                 SELECT array_agg(a.attname::text ORDER BY a.attname)
                   FROM unnest(c.conkey) k
                   JOIN pg_attribute a
                     ON a.attrelid = c.conrelid AND a.attnum = k
               ) = ARRAY['email']
            """)).scalars()
    return list(filas)


def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Columnas de identidad en `users`
    # ------------------------------------------------------------------
    if not _existe_columna(conn, "users", "external_id"):
        # Nace NULL: el backfill de mas abajo la llena y solo entonces pasa a
        # NOT NULL. Al reves, la propia migracion no podria correr.
        op.execute("ALTER TABLE public.users ADD COLUMN external_id text NULL")

    if not _existe_columna(conn, "users", "identity_provider"):
        valores = ", ".join(f"'{p}'" for p in _PROVEEDORES)
        op.execute(f"""
            ALTER TABLE public.users
              ADD COLUMN identity_provider text NOT NULL DEFAULT 'cognito',
              ADD CONSTRAINT ck_users_identity_provider
                CHECK (identity_provider IN ({valores}))
            """)

    if not _existe_columna(conn, "users", "brand_account_id"):
        # RESTRICT y no CASCADE: borrar una cuenta de marca no puede llevarse
        # por delante credenciales en silencio. Que falle y que alguien decida.
        op.execute("""
            ALTER TABLE public.users
              ADD COLUMN brand_account_id uuid NULL
              REFERENCES public.accounts(id) ON DELETE RESTRICT
            """)

    # ------------------------------------------------------------------
    # 2. El trigger que sostiene la ventana entre los dos releases
    # ------------------------------------------------------------------
    # Solo rellena cuando viene vacio. No sigue los cambios de correo a
    # proposito: el username de Cognito es inmutable, asi que un usuario que
    # cambia de correo conserva el handle con el que se autentica. Escribir
    # `external_id` desde la aplicacion —lo que hara la rebanada B con los
    # UUID— gana siempre, que es lo contrario de lo que hace el trigger de
    # `account_path` en la 027 y aqui es lo correcto: esto es un relleno de
    # transicion, no un invariante de aislamiento.
    op.execute("""
        CREATE OR REPLACE FUNCTION public.users_identidad_before()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $fn$
        BEGIN
          IF NEW.external_id IS NULL THEN
            NEW.external_id := NEW.email;
          END IF;
          RETURN NEW;
        END;
        $fn$
        """)

    op.execute("DROP TRIGGER IF EXISTS users_identidad_before ON public.users")
    op.execute("""
        CREATE TRIGGER users_identidad_before
        BEFORE INSERT OR UPDATE OF external_id, email
        ON public.users
        FOR EACH ROW
        EXECUTE FUNCTION public.users_identidad_before()
        """)

    # ------------------------------------------------------------------
    # 3. Backfill y NOT NULL
    # ------------------------------------------------------------------
    # El correo es el username en Cognito para todo usuario creado por esta
    # aplicacion. Ver la cabecera y el paso 1 del runbook: la comprobacion
    # contra el pool va **antes** de este despliegue, no despues.
    op.execute("""
        UPDATE public.users
           SET external_id = email
         WHERE external_id IS NULL
        """)
    op.execute("ALTER TABLE public.users ALTER COLUMN external_id SET NOT NULL")

    # ------------------------------------------------------------------
    # 4. La unicidad, que es el punto de la fase
    # ------------------------------------------------------------------
    # Dos indices y no uno porque `brand_account_id` admite NULL y en Postgres
    # dos NULL no chocan. Juntos cubren la tabla entera sin solaparse: o la
    # marca esta puesta, o no lo esta.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_marca_correo
          ON public.users (brand_account_id, email)
          WHERE brand_account_id IS NOT NULL
        """)
    # La marca por defecto conserva exactamente el invariante de hoy: un correo,
    # un usuario. Sin este indice, quitar `users_email_key` dejaria sin
    # proteccion a todos los usuarios que ya existen.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_correo_marca_por_defecto
          ON public.users (email)
          WHERE brand_account_id IS NULL
        """)
    # El handle es unico dentro de su proveedor, no globalmente: el dia que una
    # marca se enrute a otro IdP, nada impide que alli exista un handle que en
    # Cognito ya se use.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_proveedor_external_id
          ON public.users (identity_provider, external_id)
        """)

    # Y solo ahora, con los dos indices parciales en su sitio, se puede quitar
    # la unicidad global. En este orden no hay ni un instante sin cobertura.
    for nombre in _restricciones_unicas_de_solo_correo(conn):
        op.execute(f'ALTER TABLE public.users DROP CONSTRAINT "{nombre}"')

    # ------------------------------------------------------------------
    # 5. Enrutamiento de proveedor por cuenta (§5, regla 2)
    # ------------------------------------------------------------------
    # Por cuenta y no por variable de entorno: si el proveedor fuera global,
    # mover a un partner enterprise a WorkOS obligaria a mover a todos. NULL =
    # hereda el proveedor por defecto del despliegue.
    if not _existe_columna(conn, "accounts", "identity_provider"):
        valores = ", ".join(f"'{p}'" for p in _PROVEEDORES)
        op.execute(f"""
            ALTER TABLE public.accounts
              ADD COLUMN identity_provider text NULL,
              ADD CONSTRAINT ck_accounts_identity_provider
                CHECK (identity_provider IS NULL
                       OR identity_provider IN ({valores}))
            """)

    if not _existe_columna(conn, "accounts", "idp_config"):
        # Configuracion, nunca credenciales: lo que va aqui son identificadores
        # de conexion y referencias a Secrets Manager. Un secreto en una
        # columna jsonb acaba en cada respaldo, en cada dump de soporte y en
        # cada log de consulta lenta.
        op.execute("""
            ALTER TABLE public.accounts
              ADD COLUMN idp_config jsonb NOT NULL DEFAULT '{}'::jsonb,
              ADD CONSTRAINT ck_accounts_idp_config_objeto
                CHECK (jsonb_typeof(idp_config) = 'object')
            """)


def downgrade() -> None:
    conn = op.get_bind()

    # La unicidad global de correo solo se puede reponer si sigue siendo
    # cierta. Si dos marcas ya comparten uno, reponerla exigiria borrar
    # usuarios, y eso no lo decide una migracion.
    duplicados = conn.execute(sa.text("""
            SELECT count(*) FROM (
              SELECT email FROM public.users
               GROUP BY email HAVING count(*) > 1
            ) d
            """)).scalar()
    if duplicados:
        raise RuntimeError(
            f"no se puede revertir la 028: hay {duplicados} correo(s) repetidos "
            "entre marcas y `users_email_key` volveria a exigir unicidad global. "
            "Ver la seccion de reversion de docs/runbooks/desplegar-identidad.md"
        )

    op.execute(
        "ALTER TABLE public.accounts DROP CONSTRAINT IF EXISTS "
        "ck_accounts_idp_config_objeto"
    )
    op.execute("ALTER TABLE public.accounts DROP COLUMN IF EXISTS idp_config")
    op.execute(
        "ALTER TABLE public.accounts DROP CONSTRAINT IF EXISTS "
        "ck_accounts_identity_provider"
    )
    op.execute("ALTER TABLE public.accounts DROP COLUMN IF EXISTS identity_provider")

    if not _existe_restriccion(conn, "users_email_key"):
        op.execute("""
            ALTER TABLE public.users
              ADD CONSTRAINT users_email_key UNIQUE (email)
            """)

    op.execute("DROP INDEX IF EXISTS public.uq_users_proveedor_external_id")
    op.execute("DROP INDEX IF EXISTS public.uq_users_correo_marca_por_defecto")
    op.execute("DROP INDEX IF EXISTS public.uq_users_marca_correo")

    op.execute("DROP TRIGGER IF EXISTS users_identidad_before ON public.users")
    op.execute("DROP FUNCTION IF EXISTS public.users_identidad_before()")

    op.execute("ALTER TABLE public.users DROP COLUMN IF EXISTS brand_account_id")
    op.execute(
        "ALTER TABLE public.users DROP CONSTRAINT IF EXISTS "
        "ck_users_identity_provider"
    )
    op.execute("ALTER TABLE public.users DROP COLUMN IF EXISTS identity_provider")
    op.execute("ALTER TABLE public.users DROP COLUMN IF EXISTS external_id")

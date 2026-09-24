"""La FK de users.organization_id, que el modelo afirmaba y la base no tenia

Revision ID: 030_fk_organizacion_usuario
Revises: 029_estado_de_usuario
Create Date: 2026-09-23 00:00:00.000000

QUE VIENE A CERRAR
==================
`app/models/user.py` declara la columna asi desde hace meses:

    organization_id: UUID = Field(sa_column=Column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ))

Produccion dice otra cosa —`organization_id uuid NULL`, sin restriccion—, y son
**dos** diferencias, no una: la nulabilidad y la clave foranea. Es la columna de
la que cuelga la autorizacion de 62 endpoints.

POR QUE NO ESTABA, QUE NO ES LO QUE PARECIA
===========================================
La `014` **si** crea la FK. Lo que pasa es que empieza comprobando si existe
`users.client_id` y, si no existe, hace `return`. En produccion la columna ya se
llamaba `organization_id` —el rename se habia hecho por fuera de alembic—, asi
que la migracion paso de largo entera y nadie lo noto: no fallo, no hizo nada.

Y no lo noto tampoco el comparador de deriva, porque compara **presencia de
tablas y de columnas por nombre**. No mira nulabilidad ni claves foraneas. Su
"sin deriva" es una afirmacion mas estrecha de lo que suena.

LOS DATOS, MEDIDOS CONTRA PRODUCCION ANTES DE ESCRIBIR ESTO
===========================================================
    sin_valor  apuntan_al_vacio  total
            0                 7     23

Los siete son los siete huerfanos de la `029`: filas cuyo `organization_id`
apunta a una organizacion que no existe. Se desactivaron el 22 y el 23 de
septiembre, y **eso no cambio su puntero** — `PATCH /internal/users/{id}/status`
escribe `status` y nada mas. El documento daba la FK por desbloqueada; no lo
estaba. Una FOREIGN KEY valida filas, no estados.

POR QUE `NOT VALID`, Y QUE SIGNIFICA EXACTAMENTE
================================================
`NOT VALID` **no** significa "desactivada". La restriccion se exige desde el
primer momento a **todo INSERT y UPDATE**: ninguna fila nueva podra apuntar al
vacio, que es la proteccion que se venia a comprar. Lo unico que se salta es la
verificacion de las filas que ya estaban.

Las alternativas, y por que no:

- **Ponerles NULL a las siete**: la FK pasaria, pero entonces el `SET NOT NULL`
  ya no, y el modelo seguiria mintiendo en la otra mitad. Ademas el campo del
  modelo es `UUID`, no `Optional[UUID]`: un NULL leido por el ORM es un valor
  que el tipo declara imposible.
- **Borrar las siete filas**: son usuarios con bitacora y con referencias desde
  otras tablas. Irreversible, y el beneficio es cosmetico.
- **Crearles la organizacion que falta**: descartado en §26 — "una organizacion
  fantasma creada para una fila muerta".

Asi que las siete se quedan, y se quedan **visibles**: `pg_constraint` las
declara con `convalidated = false`, que es una deuda que se puede consultar en
vez de una que hay que recordar. El dia que se decida que hacer con ellas:

    ALTER TABLE public.users VALIDATE CONSTRAINT users_organization_id_fkey;

Esa operacion no bloquea escrituras (solo toma SHARE UPDATE EXCLUSIVE) y falla
sola si todavia queda alguna apuntando al vacio.

SOBRE §26
=========
La direccion acordada el 20/09 es que las membresias son la fuente de verdad y
que esta columna acaba renombrandose a `default_organization_id` y
desapareciendo. Esta migracion no contradice eso: defiende la columna mientras
siga gobernando la autorizacion, y las dos cosas que hace se revierten en una
linea cada una.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "030_fk_organizacion_usuario"
down_revision: Union[str, None] = "029_estado_de_usuario"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT = "users_organization_id_fkey"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. No colgarse esperando un bloqueo
    # ------------------------------------------------------------------
    # Misma leccion que la 029, y por la misma razon: `users` se lee en cada
    # peticion autenticada, asi que un ALTER que espera encola detras de si a
    # todos los lectores que lleguen despues. Diez segundos y se rinde.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("SET LOCAL statement_timeout = '5min'")

    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 1. Mirar antes de tocar
    # ------------------------------------------------------------------
    # El `SET NOT NULL` de abajo falla si hay algun NULL, y su mensaje no dice
    # cuantos ni cuales. Preguntarlo aqui cuesta una consulta y convierte un
    # fallo opaco en uno que se explica solo. Es la leccion del despliegue de la
    # v1.32.1, que se descubrio el problema por un ForeignKeyViolation crudo.
    sin_valor = conn.execute(
        sa.text("SELECT count(*) FROM public.users WHERE organization_id IS NULL")
    ).scalar_one()

    apuntan_al_vacio = conn.execute(
        sa.text(
            """
            SELECT count(*)
              FROM public.users u
             WHERE u.organization_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM public.organizations o
                                WHERE o.id = u.organization_id)
            """
        )
    ).scalar_one()

    print(
        f"🔎 users.organization_id: {sin_valor} sin valor, "
        f"{apuntan_al_vacio} apuntando a una organizacion inexistente"
    )

    if sin_valor:
        raise RuntimeError(
            f"{sin_valor} usuarios tienen organization_id NULL. El modelo la "
            "declara obligatoria, asi que hay que decidir que organizacion les "
            "corresponde antes de aplicar esta migracion. Consulta:\n"
            "  SELECT id, email FROM users WHERE organization_id IS NULL;"
        )

    # ------------------------------------------------------------------
    # 2. La mitad que se puede exigir sobre lo que ya hay
    # ------------------------------------------------------------------
    # Cero NULLs hoy, asi que esto no reescribe nada ni puede fallar por datos.
    op.execute(
        "ALTER TABLE public.users ALTER COLUMN organization_id SET NOT NULL"
    )

    # ------------------------------------------------------------------
    # 3. La clave foranea, sin validar lo viejo
    # ------------------------------------------------------------------
    # NOT VALID se exige a todo lo que entre a partir de ahora; solo se salta la
    # verificacion de las filas existentes. Ver la cabecera para el porque.
    op.execute(
        f"""
        ALTER TABLE public.users
          ADD CONSTRAINT {CONSTRAINT}
          FOREIGN KEY (organization_id)
          REFERENCES public.organizations (id)
          ON DELETE CASCADE
          NOT VALID
        """
    )

    if apuntan_al_vacio:
        print(
            f"⚠️  La restriccion queda NOT VALID: {apuntan_al_vacio} filas "
            "anteriores apuntan a una organizacion que no existe. Se exige a "
            "todo lo nuevo. Cuando se decida que hacer con ellas:\n"
            f"    ALTER TABLE public.users VALIDATE CONSTRAINT {CONSTRAINT};"
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"ALTER TABLE public.users DROP CONSTRAINT IF EXISTS {CONSTRAINT}")
    op.execute("ALTER TABLE public.users ALTER COLUMN organization_id DROP NOT NULL")

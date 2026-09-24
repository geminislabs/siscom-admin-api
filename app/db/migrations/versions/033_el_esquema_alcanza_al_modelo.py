"""El esquema alcanza al modelo: 17 columnas obligatorias y 8 claves foraneas

Revision ID: 033_el_esquema_alcanza
Revises: 032_alert_rules_created_by
Create Date: 2026-09-24 00:00:00.000000

QUE ES
======
La ultima rebanada de las 30 divergencias que el comparador hizo visibles al
aprender a mirar restricciones (#110). Las cuatro donde mandaba la base se
arreglaron en el modelo (#113); `trips.end_time` resulto ser un 500 vivo y no
deuda de esquema (#114). Aqui entran las 25 restantes.

MEDIDO CONTRA PRODUCCION ANTES DE ESCRIBIR NADA
===============================================
Una consulta de solo lectura sobre las 26 candidatas. Veintitres dieron cero.
Las tres que no:

    public.plan_capabilities.plan_id   45 apuntando al vacio
    public.trips.end_time               4 nulos      -> se fue en #114
    public.trips.device_id              2 apuntando al vacio

LAS CUARENTA Y CINCO DE plan_capabilities
=========================================
Son configuracion de planes que ya no existen, y son **inalcanzables**: a una
`plan_capability` se llega por su plan. Con el plan borrado, esas filas no las
puede leer ninguna consulta del sistema — ni la resolucion de capabilities, que
es `organization_override ?? plan_capability ?? default` y entra por el plan de
la suscripcion.

**Se borran**, decision de Jesus, y la FK entra validada. La alternativa era
dejarlas y vivir con un `NOT VALID` permanente por 45 filas que nadie puede
leer.

El borrado esta acotado: si el numero se dispara respecto a lo medido, la
migracion se planta. Cuarenta y cinco filas muertas son una limpieza; cuatro mil
serian otra cosa, y no una que deba decidir una migracion a las dos de la
mañana.

LAS DOS DE trips
================
Viajes cuyo equipo se dio de baja. Aqui **no** se borra: tirar historial de
viajes para satisfacer una restriccion es mal negocio, y son dos. Su FK entra
`NOT VALID` — se exige a todo lo nuevo, y esas dos quedan contadas en
`pg_constraint` como las siete de `users`.

EL `ON DELETE` DE CADA UNA
==========================
Sale de lo que declara el modelo, leido de su metadata, no de lo que parezca
razonable. Cuatro declaran `CASCADE` y cuatro no declaran nada — y `NO ACTION`
es una decision tan valida como la otra. Inventarle un CASCADE a `orders` seria
decidir que borrar una organizacion borra su historial de pedidos.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "033_el_esquema_alcanza"
down_revision: Union[str, None] = "032_alert_rules_created_by"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Lo medido el 24/09. Si la realidad se aleja de esto, la migracion se planta
# en vez de seguir: el numero es parte de la decision, no un detalle.
HUERFANAS_ESPERADAS = 45
TECHO_DE_LIMPIEZA = 200


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. No colgarse esperando un bloqueo
    # ------------------------------------------------------------------
    # Misma leccion de la 029 en adelante. Aqui ademas hay tablas que pueden
    # ser grandes, asi que el statement_timeout cubre los recorridos.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("SET LOCAL statement_timeout = '10min'")

    conn = op.get_bind()

    # ------------------------------------------------------------------
    # 2. La limpieza de plan_capabilities, acotada
    # ------------------------------------------------------------------
    huerfanas = conn.execute(sa.text("""
            SELECT count(*) FROM public.plan_capabilities pc
             WHERE NOT EXISTS (SELECT 1 FROM public.plans p WHERE p.id = pc.plan_id)
            """)).scalar_one()

    print(
        f"🔎 plan_capabilities apuntando a un plan inexistente: {huerfanas} "
        f"(medidas el 24/09: {HUERFANAS_ESPERADAS})"
    )

    if huerfanas > TECHO_DE_LIMPIEZA:
        raise RuntimeError(
            f"{huerfanas} filas huerfanas en plan_capabilities, muy por encima de "
            f"las {HUERFANAS_ESPERADAS} medidas. Borrar esa cantidad no es la "
            "limpieza que se aprobo: hay que mirar que paso antes de seguir."
        )

    if huerfanas:
        conn.execute(sa.text("""
                DELETE FROM public.plan_capabilities pc
                 WHERE NOT EXISTS (SELECT 1 FROM public.plans p
                                    WHERE p.id = pc.plan_id)
                """))
        print(f"🧹 borradas {huerfanas} filas de configuracion inalcanzable")

    # ------------------------------------------------------------------
    # 3. Las diecisiete columnas que pasan a obligatorias
    # ------------------------------------------------------------------
    # Todas midieron cero nulos. `SET NOT NULL` recorre la tabla una vez bajo
    # ACCESS EXCLUSIVE; en las grandes (`commands`, `devices`) eso es lo unico
    # que puede tardar, y para eso esta el statement_timeout de arriba. Si
    # alguna se pasa, la migracion aborta entera sin dejar nada a medias.
    op.execute("ALTER TABLE api_platform.api_alerts ALTER COLUMN enabled SET NOT NULL")
    op.execute("ALTER TABLE public.commands ALTER COLUMN requested_at SET NOT NULL")
    op.execute("ALTER TABLE public.commands ALTER COLUMN updated_at SET NOT NULL")
    op.execute("ALTER TABLE public.devices ALTER COLUMN created_at SET NOT NULL")
    op.execute("ALTER TABLE public.devices ALTER COLUMN updated_at SET NOT NULL")
    op.execute(
        "ALTER TABLE public.invitations ALTER COLUMN organization_id SET NOT NULL"
    )
    op.execute("ALTER TABLE public.order_items ALTER COLUMN description SET NOT NULL")
    op.execute("ALTER TABLE public.order_items ALTER COLUMN item_type SET NOT NULL")
    op.execute("ALTER TABLE public.order_items ALTER COLUMN total_price SET NOT NULL")
    op.execute("ALTER TABLE public.orders ALTER COLUMN created_at SET NOT NULL")
    op.execute("ALTER TABLE public.orders ALTER COLUMN organization_id SET NOT NULL")
    op.execute("ALTER TABLE public.plans ALTER COLUMN is_active SET NOT NULL")
    op.execute("ALTER TABLE public.unit_profile ALTER COLUMN created_at SET NOT NULL")
    op.execute("ALTER TABLE public.unit_profile ALTER COLUMN updated_at SET NOT NULL")
    op.execute("ALTER TABLE public.user_devices ALTER COLUMN is_active SET NOT NULL")
    op.execute(
        "ALTER TABLE public.vehicle_profile ALTER COLUMN created_at SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE public.vehicle_profile ALTER COLUMN updated_at SET NOT NULL"
    )

    # ------------------------------------------------------------------
    # 4. Las siete claves foraneas, validadas
    # ------------------------------------------------------------------
    # El `ON DELETE` de cada una sale de lo que declara el modelo, no de lo que
    # parezca razonable: la mitad no declara ninguno, y NO ACTION es una
    # decision tan valida como CASCADE.
    op.execute("""
        ALTER TABLE public.invitations
          ADD CONSTRAINT invitations_organization_id_fkey
          FOREIGN KEY (organization_id)
          REFERENCES public.organizations (id)
          ON DELETE CASCADE
        """)

    op.execute("""
        ALTER TABLE public.orders
          ADD CONSTRAINT orders_organization_id_fkey
          FOREIGN KEY (organization_id)
          REFERENCES public.organizations (id)
        """)

    op.execute("""
        ALTER TABLE public.orders
          ADD CONSTRAINT orders_payment_id_fkey
          FOREIGN KEY (payment_id)
          REFERENCES public.payments (id)
        """)

    op.execute("""
        ALTER TABLE public.plan_capabilities
          ADD CONSTRAINT plan_capabilities_plan_id_fkey
          FOREIGN KEY (plan_id)
          REFERENCES public.plans (id)
        """)

    op.execute("""
        ALTER TABLE public.subscriptions
          ADD CONSTRAINT subscriptions_organization_id_fkey
          FOREIGN KEY (organization_id)
          REFERENCES public.organizations (id)
          ON DELETE CASCADE
        """)

    op.execute("""
        ALTER TABLE public.subscriptions
          ADD CONSTRAINT subscriptions_plan_id_fkey
          FOREIGN KEY (plan_id)
          REFERENCES public.plans (id)
        """)

    op.execute("""
        ALTER TABLE public.tokens_confirmacion
          ADD CONSTRAINT tokens_confirmacion_organization_id_fkey
          FOREIGN KEY (organization_id)
          REFERENCES public.organizations (id)
          ON DELETE CASCADE
        """)

    # ------------------------------------------------------------------
    # 5. La de trips, sin validar lo viejo
    # ------------------------------------------------------------------
    # Dos viajes de equipos dados de baja. No se borran: el historial vale mas
    # que la validez retroactiva de la restriccion.
    op.execute("""
        ALTER TABLE public.trips
          ADD CONSTRAINT trips_device_id_fkey
          FOREIGN KEY (device_id)
          REFERENCES public.devices (device_id)
          ON DELETE CASCADE
          NOT VALID
        """)


def downgrade() -> None:
    """Quita lo que puso. No devuelve las 45 filas: un borrado no se deshace.

    Si hiciera falta recuperarlas, sale de una copia de seguridad, no de aqui —
    y conviene saberlo antes de necesitarlo.
    """
    op.execute("SET LOCAL lock_timeout = '10s'")

    for tabla, columna in (
        ("trips", "device_id"),
        ("tokens_confirmacion", "organization_id"),
        ("subscriptions", "plan_id"),
        ("subscriptions", "organization_id"),
        ("plan_capabilities", "plan_id"),
        ("orders", "payment_id"),
        ("orders", "organization_id"),
        ("invitations", "organization_id"),
    ):
        op.execute(
            f"ALTER TABLE public.{tabla} "
            f"DROP CONSTRAINT IF EXISTS {tabla}_{columna}_fkey"
        )

    for esquema, tabla, columna in (
        ("api_platform", "api_alerts", "enabled"),
        ("public", "commands", "requested_at"),
        ("public", "commands", "updated_at"),
        ("public", "devices", "created_at"),
        ("public", "devices", "updated_at"),
        ("public", "invitations", "organization_id"),
        ("public", "order_items", "description"),
        ("public", "order_items", "item_type"),
        ("public", "order_items", "total_price"),
        ("public", "orders", "created_at"),
        ("public", "orders", "organization_id"),
        ("public", "plans", "is_active"),
        ("public", "unit_profile", "created_at"),
        ("public", "unit_profile", "updated_at"),
        ("public", "user_devices", "is_active"),
        ("public", "vehicle_profile", "created_at"),
        ("public", "vehicle_profile", "updated_at"),
    ):
        op.execute(
            f"ALTER TABLE {esquema}.{tabla} " f"ALTER COLUMN {columna} DROP NOT NULL"
        )

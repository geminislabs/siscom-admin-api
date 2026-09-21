"""Estado del usuario, y la membresia OWNER que el fallback de is_master suplia

Revision ID: 029_estado_de_usuario
Revises: 028_identidad_esquema
Create Date: 2026-09-20 00:00:00.000000

QUE ES Y QUE NO ES
==================
Es **solo esquema y datos**, igual que la 027 y la 028: ningun modelo, endpoint
ni servicio de este repositorio lee todavia `users.status`. Es la mitad "expand"
del expand/contract (§18) — la migracion viaja en un release y el codigo que la
usa en el siguiente.

EL FALLO VIVO QUE VIENE A DESTRABAR
===================================
Hoy no hay forma de dar de baja a un usuario, y eso produce un callejon sin
salida que ya ocurre en produccion:

  1. Un admin quita a alguien de la organizacion
     (`DELETE /{org}/users/{user_id}`): se borra **la membresia**, y la fila de
     `users` sobrevive intacta, con su correo y su credencial.
  2. Meses despues lo vuelven a invitar: `invite_user` busca por correo
     (`users.py:82`), encuentra la fila y responde 400.
  3. No hay salida por la API — no existe ningun endpoint que borre un usuario,
     y no habia columna de estado. Solo se arreglaba con SQL a mano.

Y **relajar la comprobacion no era una opcion**: los indices de la 028
(`uq_users_marca_correo` y `uq_users_correo_marca_por_defecto`) no filtran por
estado, asi que aunque la aplicacion dejara pasar el alta, Postgres la rechaza.
La respuesta correcta es **reactivar la fila existente**, no crear otra — que
ademas conserva el handle de Cognito, que es inmutable y sigue siendo valido.
Esta migracion pone la columna que hace posible esa reactivacion.

POR QUE SOLO DOS VALORES
========================
`ACTIVE` e `INACTIVE`, y nada mas. Anadir `SUSPENDED` o `PENDING` ahora seria
sembrar codigos sin semantica acordada, que es exactamente lo que la 027 evito
al no sembrar `self_signup_mode`: un valor sin significado acordado invita a que
alguien le invente uno. Cuando el cierre de cuentas defina mas estados, se
anaden con su CHECK.

EL RELLENO, Y POR QUE NO ES OPCIONAL
====================================
`OrganizationService.get_user_role` resuelve el rol por membresia, pero tiene un
fallback heredado (`app/services/organization.py:78-81`): sin membresia, si
`user.organization_id` coincide y `user.is_master` es cierto, devuelve OWNER.

Ese fallback es la segunda fuente de verdad sobre "que rol tiene esta persona
aqui", y produce un fallo propio: a un master al que le borran la membresia
**no se le quita el rol**. La salida limpia no es anadirle una condicion sino
quitarlo — y para poder quitarlo, todo usuario que hoy dependa de el necesita su
membresia explicita.

**Medido contra produccion el 20/09/2026**: siete usuarios con `is_master` y sin
membresia OWNER en su organizacion, y los siete **sin ningun evento
`org_user_removed`** en `account_events`. Es decir, los siete son masters
heredados —de antes de que `organization_users` existiera— y ninguno es alguien
a quien sacaron a proposito. Uno de ellos es la cuenta del propio Jesus: quitar
el fallback sin este relleno le habria costado el OWNER de su organizacion.

El filtro por `account_events` se conserva en el INSERT **aunque hoy no excluya
a nadie**. Cuesta un NOT EXISTS y hace la migracion auto-correctiva: si entre
esta medicion y el despliegue alguien quita a un master a proposito, el relleno
no le devuelve el rol en silencio. Una migracion que depende de que los datos no
se muevan entre que se mide y se aplica es una migracion que miente.

El NOT EXISTS de membresia **no filtra por rol**, a proposito. La consulta que
midio los siete si lo hacia (`ou.role = 'owner'`), pero insertar con ese criterio
podria crear una segunda fila para un usuario que ya tiene membresia con otro rol
y violar `uq_org_user`. Quien tenga una membresia explicita —sea cual sea su
rol— ya resuelve por ella y el fallback no le afecta: se deja como esta.

POR QUE EL DOWNGRADE NO DESHACE EL RELLENO
==========================================
Decision de Jesus, 20/09/2026, y conviene que este escrita porque el guardian de
CI de la cadena exige `downgrade()` con cuerpo real y este lo tiene: quita la
columna y su CHECK.

Lo que no hace es tocar las membresias, y no por descuido. El relleno **no
concede nada nuevo**: materializa el rol que esas siete personas ya tienen hoy a
traves del fallback. Revertir la columna de estado no es razon para quitarselo, y
borrarlas dejaria a esos usuarios peor de lo que estaban antes de esta migracion.
El relleno es, en ese sentido, irreversible a proposito.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "029_estado_de_usuario"
down_revision: Union[str, None] = "028_identidad_esquema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ESTADOS = ("ACTIVE", "INACTIVE")


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. No colgarse esperando un bloqueo
    # ------------------------------------------------------------------
    # El primer intento de desplegar esta migracion (v1.32.0, 21/09/2026) se
    # quedo **colgado 9 minutos y 42 segundos** en el `ADD COLUMN` de abajo,
    # hasta que el canal SSH del despliegue se rindio por timeout. No fallo: se
    # colgo, que es peor.
    #
    # `ALTER TABLE` necesita ACCESS EXCLUSIVE sobre `users`, y `users` se lee en
    # **cada peticion autenticada** (`deps.py` busca por `cognito_sub`). Si algo
    # tiene la tabla tomada, el ALTER espera; y mientras espera, **los lectores
    # que llegan despues se encolan detras de el**. Una operacion que en PG15 es
    # de metadatos —sin reescritura de tabla— se convirtio en diez minutos de
    # autenticacion degradada.
    #
    # `lock_timeout` convierte eso en un fallo de diez segundos que no toca
    # nada: el despliegue aborta antes de sustituir el contenedor, el servicio
    # anterior sigue sirviendo, y el mensaje de error **nombra el bloqueo**, que
    # es justo el diagnostico que la primera vez hubo que ir a buscar a mano.
    #
    # `statement_timeout` cubre lo otro que podria tardar, el relleno del paso
    # 2. Hoy son siete filas, pero el `NOT EXISTS` contra `account_events`
    # recorre una tabla de auditoria que solo crece.
    #
    # LOCAL y no global: revierte al cerrar la transaccion de alembic, asi que
    # no deja configuracion pegada a la sesion.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("SET LOCAL statement_timeout = '5min'")

    # ------------------------------------------------------------------
    # 1. La columna de estado
    # ------------------------------------------------------------------
    # NOT NULL con DEFAULT desde el principio: toda fila existente nace
    # ACTIVE, que es lo que son hoy —no hay forma de desactivar a nadie—, y el
    # codigo viejo sigue insertando sin mencionarla.
    #
    # CHECK y no ENUM, misma razon que `account_type` en la 027: anadir un
    # estado nuevo a un ENUM en Postgres es una operacion con mas aristas que
    # reescribir un CHECK, y aqui se espera anadir estados cuando el cierre de
    # cuentas los defina.
    op.execute("""
        ALTER TABLE public.users
          ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'ACTIVE'
        """)

    op.execute("""
        ALTER TABLE public.users
          DROP CONSTRAINT IF EXISTS ck_users_status
        """)
    op.execute("""
        ALTER TABLE public.users
          ADD CONSTRAINT ck_users_status
          CHECK (status IN ('ACTIVE', 'INACTIVE'))
        """)

    # ------------------------------------------------------------------
    # 2. La membresia OWNER de los masters heredados
    # ------------------------------------------------------------------
    # Ver la cabecera: esto es lo que permite borrar el fallback de is_master en
    # la rebanada de codigo sin quitarle el rol a nadie.
    #
    # Idempotente por los dos NOT EXISTS: correrla dos veces no inserta nada la
    # segunda vez.
    op.execute("""
        INSERT INTO public.organization_users (organization_id, user_id, role)
        SELECT u.organization_id, u.id, 'owner'
          FROM public.users u
         WHERE u.is_master
           AND u.organization_id IS NOT NULL
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
    # Quita la columna y su CHECK. **No** toca las membresias del paso 2 — ver
    # la cabecera: materializan un rol que esas personas ya tenian por el
    # fallback, y borrarlas las dejaria peor que antes de esta migracion.
    op.execute("""
        ALTER TABLE public.users
          DROP CONSTRAINT IF EXISTS ck_users_status
        """)
    op.execute("""
        ALTER TABLE public.users
          DROP COLUMN IF EXISTS status
        """)

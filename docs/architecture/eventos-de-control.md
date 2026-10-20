# Eventos de control: el contrato de `control-plane-events`

> **Estado:** en producción desde el 19/10/2026 (admin-api `v1.60.0`,
> event-processor `v1.3.0`, alert-distributor `v0.3.0`), junto con el
> [ADR-008](./adr/008-eventos-de-control-en-un-topic.md). admin-api ya no escribe
> los topics viejos (`user-devices-updates`, `unit-devices-updates`,
> `user-units-updates`): `control-plane-events` es el único.

Este documento es la fuente de verdad del mensaje. El *porqué* de un solo topic,
una partición y sin outbox está en el ADR-008; aquí está el *qué*: el sobre, el
`data` de cada entidad, quién lo emite y las reglas para cambiarlo.

Cada consumidor documenta en su propio repo qué entidades lee y cómo las aplica,
con un enlace aquí. No copia el contrato.

---

## 1. El topic

| Propiedad | Valor |
|---|---|
| Nombre | `control-plane-events` |
| Particiones | **1** (orden total entre entidades; ADR-008 §3) |
| Key | `"{entity}:{id}"`, ver la tabla de §3 |
| Valor | JSON UTF-8, un objeto por mensaje |
| Retención | La del clúster; nadie depende de releer la historia |
| Compaction | No |
| Productor | Solo `siscom-admin-api` |

## 2. El sobre

```json
{
  "schema_version": 1,
  "event_id": "8c1f…",
  "event_type": "UPSERT",
  "entity": "organization_user",
  "timestamp": "2026-10-19T18:04:11.402Z",
  "organization_id": "c24ba579-…",
  "data": { }
}
```

| Campo | Tipo | Significado |
|---|---|---|
| `schema_version` | entero | Versión del `data` **de esa entidad**. Empieza en `1`. |
| `event_id` | UUID | Único por mensaje. Sirve para trazar, no para deduplicar. |
| `event_type` | `UPSERT` \| `DELETE` | `UPSERT`: la fila existe con este estado. `DELETE`: la fila dejó de existir. |
| `entity` | texto | Una de las de §3. Un consumidor **ignora** las que no conoce. |
| `timestamp` | ISO-8601 UTC con `Z` | Momento de publicación, no del cambio. |
| `organization_id` | UUID o `null` | Organización del cambio, informativa. **No** se usa para indexar: lo que importa está en `data`. |
| `data` | objeto | En `UPSERT`, estado **completo** de la fila (§3), nunca un delta. En `DELETE`, solo los campos de la clave. |

**`UPSERT` con `is_active: false` o `status: "INACTIVE"` no es un `DELETE`.** La
fila sigue existiendo y puede reactivarse. `DELETE` se reserva para filas que se
borran de verdad (`organization_users` al quitar a alguien, `user_units` al
revocar).

> Cambio respecto al topic viejo: `user-devices-updates` publicaba `DELETE` al
> desactivar un dispositivo, aunque la fila siguiera existiendo. En
> `control-plane-events` eso es un `UPSERT` con `is_active: false`.

### Cómo se emite

Ningún endpoint publica estos eventos. Un listener de la sesión del ORM
(`app/services/messaging/control_plane.py`) anota en cada flush qué claves se
tocaron y, después del commit, lee la fila de cada una **desde su vista** (§4):
si existe, `UPSERT` con esa fila; si no, `DELETE` con la clave. Así:

- toda escritura emite, la haga el endpoint, el servicio o el script que sea;
- el evento y la foto de arranque salen de la misma vista y no pueden divergir;
- lo único que se salta la emisión es escribir sin el ORM (`query(...).update()`,
  `.delete()` o SQL crudo sobre estas tablas), y
  `tests/test_control_plane_sin_escrituras_masivas.py` falla si aparece.

Las tablas «Dónde» de §3 son el inventario de lo que hoy escribe cada entidad,
para orientarse; no son una lista que haya que mantener.

## 3. Entidades

### `user`

Estado de la persona en el sistema. Distinto del de cada membresía: alguien puede
tener una membresía `ACTIVE` y estar dado de baja como usuario.

| Key | `user:{id}` |
|---|---|

```json
{ "id": "17e28261-…", "status": "ACTIVE" }
```

| Campo | Tipo | Notas |
|---|---|---|
| `id` | UUID | `users.id` |
| `status` | `ACTIVE` \| `INACTIVE` | `users.status` |

Se emite `UPSERT` en:

| Dónde | Cuándo |
|---|---|
| `auth.py` · `POST /auth/register` | Alta |
| `users.py` · `POST /users/accept-invitation` | Alta, o readmisión de un usuario `INACTIVE` |
| `organization_users.py` · `DELETE /organizations/{org}/users/{user}` | Si era su última membresía activa y pasa a `INACTIVE` |
| `internal/users.py` · `PATCH /internal/users/{id}/status` | Baja o readmisión desde GAC |

No hay `DELETE`: los usuarios no se borran por API.

### `organization_user`

Una membresía: quién pertenece a qué organización, con qué rol y si está activa.

| Key | `organization_user:{organization_id}:{user_id}` |
|---|---|

```json
{
  "organization_id": "c24ba579-…",
  "user_id": "17e28261-…",
  "role": "owner",
  "status": "ACTIVE"
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `organization_id` | UUID | |
| `user_id` | UUID | |
| `role` | `owner` \| `admin` \| `billing` \| `member` | `OrganizationRole` |
| `status` | `ACTIVE` \| `INACTIVE` | `MembershipStatus`. Pausar y reactivar son `UPSERT` con distinto valor. |

| Dónde | `event_type` | Cuándo |
|---|---|---|
| `auth.py` · `POST /auth/register` | `UPSERT` | Membresía `owner` de la organización nueva |
| `organizations.py` · `POST /organizations` | `UPSERT` | Membresía `owner` de quien la crea |
| `users.py` · `POST /users/accept-invitation` | `UPSERT` | Alta o reactivación |
| `organization_users.py` · `POST /organizations/{org}/users` | `UPSERT` | Alta de un usuario existente |
| `organization_users.py` · `PATCH /organizations/{org}/users/{user}` | `UPSERT` | Cambio de rol |
| `organization_users.py` · `PATCH /organizations/{org}/users/{user}/status` | `UPSERT` | Pausa o reactivación |
| `organization_users.py` · `DELETE /organizations/{org}/users/{user}` | `DELETE` | Baja de la membresía |

`OrganizationService.add_member`, `update_member_role` y `remove_member` también
escriben membresías, aunque hoy ninguna ruta los llama. Si se usan, emiten igual:
la emisión es del ORM (§2, «Cómo se emite»).

### `user_unit`

Una unidad concedida a un usuario que no es `owner`.

| Key | `user_unit:{user_id}:{unit_id}` |
|---|---|

```json
{
  "organization_id": "c24ba579-…",
  "user_id": "61e5f8a1-…",
  "unit_id": "482a054c-…",
  "role": "viewer"
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `organization_id` | UUID | De la unidad. **Nuevo** en `data`: hoy solo va en el sobre. |
| `user_id` | UUID | |
| `unit_id` | UUID | |
| `role` | texto | `user_units.role` |

| Dónde | `event_type` |
|---|---|
| `units.py` · `POST /units/{unit_id}/users` | `UPSERT` |
| `units.py` · `DELETE /units/{unit_id}/users/{user_id}` | `DELETE` |
| `user_units.py` · `POST /user-units` | `UPSERT` |
| `user_units.py` · `DELETE /user-units/{assignment_id}` | `DELETE` |

### `unit_device`

Qué GPS está instalado en qué unidad. De aquí sale la relación unidad →
organización que necesitan los consumidores.

| Key | `unit_device:{device_id}` |
|---|---|

```json
{
  "device_id": "866…",
  "unit_id": "482a054c-…",
  "organization_id": "23f7dcc8-…"
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `device_id` | texto | IMEI |
| `unit_id` | UUID | La unidad de su asignación vigente |
| `organization_id` | UUID | De esa unidad |

`UPSERT` mientras el equipo tiene una asignación vigente (`unassigned_at IS NULL`)
en una unidad no borrada; `DELETE` cuando deja de tenerla. Si un equipo se mueve
de unidad, el `UPSERT` trae la nueva: con estado completo no hace falta decir
cuál era la anterior. Se escribe en:

| Dónde | Cuándo |
|---|---|
| `units.py` · `POST /units` | Unidad creada con equipo |
| `units.py` · `POST /units/{unit_id}/device` | Asignación (y liberación del anterior: dos eventos) |
| `unit_devices.py` · `POST /unit-devices` | Asignación |
| `unit_devices.py` · `DELETE /unit-devices/{assignment_id}` | Desasignación |
| `devices.py` · `PATCH /devices/{device_id}/status` | Cambios de estado que asignan o liberan |

Borrar una unidad (lógicamente) o moverla de organización publica de nuevo sus
concesiones (`user_unit`) y su equipo (`unit_device`), aunque esas filas no se
toquen: las vistas dejan de mostrarlas, o las muestran con otra organización.

### `user_device`

Un dispositivo móvil registrado para push.

| Key | `user_device:{id}` |
|---|---|

```json
{
  "id": "0669de69-…",
  "user_id": "17e28261-…",
  "device_token": "e3gXCIFnQ0ivlQ53…",
  "platform": "ios",
  "endpoint_arn": "arn:aws:sns:us-east-1:…:endpoint/GCM/siscom-alerts/…",
  "is_active": true,
  "updated_at": "2026-10-19T01:00:16.118Z"
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `id` | UUID | `user_devices.id` |
| `user_id` | UUID | Un dispositivo es de la **persona**, no de una organización. Los consumidores lo indexan por `user_id`. |
| `device_token` | texto | Token FCM |
| `platform` | `ios` \| `android` | |
| `endpoint_arn` | texto o `null` | Endpoint de SNS |
| `is_active` | booleano | |
| `updated_at` | ISO-8601 UTC | |

Siempre `UPSERT`. Se escribe en:

| Dónde | Cuándo |
|---|---|
| `user_devices.py` · `POST /user-devices/register` | Alta o reactivación; también para la fila de **otra** cuenta que se desactiva en un aparato compartido |
| `user_devices.py` · `POST /user-devices/deactivate` | `is_active: false` |

Cuando `alert-distributor` desactiva un endpoint que SNS rechaza, escribe
directo en `user_devices` y **no** publica: es el único que lo necesita y ya
actualizó su caché.

## 4. La foto de arranque: vistas `control_plane.*`

Un consumidor arranca leyendo el estado actual (ADR-008 §4). Lo lee de vistas
que admin-api crea por migración en el esquema `control_plane`, **nunca** de
las tablas. Cada vista tiene exactamente las columnas del `data` de su entidad
(§3), con los mismos nombres y tipos:

| Vista | Filas |
|---|---|
| `control_plane.users` | Todos los usuarios |
| `control_plane.organization_users` | Todas las membresías, de cualquier `status` |
| `control_plane.user_units` | Todas las concesiones, de unidades no borradas |
| `control_plane.unit_devices` | Asignaciones vigentes (`unassigned_at IS NULL`) de unidades no borradas |
| `control_plane.user_devices` | Todos los dispositivos, de cualquier `is_active` |

Las vistas no filtran por permisos ni aplican la regla de visibilidad; eso es
cosa de cada consumidor. Un test de esquema de admin-api, sobre la base migrada,
falla si una vista falta o si sus columnas no coinciden con §3.

## 5. Reglas para cambiar el contrato

1. **Añadir un campo** a un `data` es compatible: no sube `schema_version`, y
   los consumidores ignoran campos que no conocen. La vista gana la columna en
   el mismo PR.
2. **Quitar un campo, cambiar su tipo o su significado** sube `schema_version`
   de esa entidad. Durante la transición se publican las dos versiones, y la
   vieja se retira cuando ningún consumidor la lea (tabla de §6).
3. **Renombrar o quitar una columna de una tabla** obliga a mantener viva la
   vista que la expone. Si no se puede, aplica la regla 2.
4. **Añadir una entidad** no cambia la versión de las demás. Se documenta aquí
   en el mismo PR que la emite, con su vista.
5. Todo PR que toque un evento o una vista actualiza este documento. Si no lo
   actualiza, el PR no está completo.

## 6. Consumidores

| Servicio | Entidades | Para qué | Documento |
|---|---|---|---|
| `event-processor` | `unit_device` | Atribuir cada mensaje GPS a su unidad vigente | `event-processor/docs/eventos-de-control.md` (pendiente) |
| `alert-distributor` | todas | Destinatarios de push y del WebSocket de alertas | `alert-distributor/docs/eventos-de-control.md` (pendiente) |

Un consumidor nuevo añade su fila aquí y su documento en su repo, y pide la ACL
de lectura del topic y el `GRANT SELECT` sobre `control_plane`.

## 7. Operación

Los comandos los ejecuta quien administra el clúster. `siscom-admin-api` es el
único usuario con que admin-api produce, en este topic y en todos los demás
(ADR-008 §8, desde el 20/10/2026), y llega en `KAFKA_SASL_USERNAME` /
`KAFKA_SASL_PASSWORD`. Hasta `v1.62.1` este topic tenía además sus propias
variables `KAFKA_CONTROL_PLANE_SASL_*`; se quitaron al quedar todo en el mismo
usuario.

En admin-api, la emisión se enciende con la variable de GitHub
`KAFKA_CONTROL_PLANE_TOPIC=control-plane-events`. Sin ella, el topic queda vacío
y no se publica nada: un despliegue no puede encenderla antes de que existan el
topic y las ACL.

En la base, la migración `044` da `USAGE` y `SELECT` sobre `control_plane` al
`DB_USER` de admin-api. `alert-distributor` y `event-processor` se conectan como
`siscom`; si ese no fuera el `DB_USER` de admin-api, necesitan:

```sql
GRANT USAGE ON SCHEMA control_plane TO siscom;
GRANT SELECT ON ALL TABLES IN SCHEMA control_plane TO siscom;
```

```bash
# Usuario del productor
rpk security user create siscom-admin-api -p '<contraseña>' --mechanism SCRAM-SHA-256

# Topic
rpk topic create control-plane-events -p 1

# admin-api escribe
rpk security acl create --allow-principal "User:siscom-admin-api" \
  --operation write,describe --topic control-plane-events

# Los consumidores leen sin grupo: no hacen commit (ADR-008 §4)
rpk security acl create --allow-principal "User:events-processor" \
  --operation read,describe --topic control-plane-events
rpk security acl create --allow-principal "User:alerts-distributor" \
  --operation read,describe --topic control-plane-events
```

Geocercas de event-processor (ADR-008, «Adopción», paso 3). No es parte de este
contrato, pero sale en la misma versión:

```bash
rpk security acl create --allow-principal "User:events-processor" \
  --operation read,describe --topic geofences-updates
rpk security acl create --allow-principal "User:events-processor" \
  --operation read,describe --group events-processor-geofences
```

Cuando admin-api deje de escribir los topics viejos (ADR-008, «Adopción»,
pasos 5 y 6):

```bash
rpk topic delete user-devices-updates user-units-updates geofences-update
rpk group delete alert-distributor-user-devices-updates alert-distributor-user-units-updates
# ACL huérfanas: rpk security acl list, y rpk security acl delete por cada una
# que apunte a un topic o grupo que ya no existe
```

Para mirar el tráfico:

```bash
rpk topic consume control-plane-events -o -20 -n 20
```

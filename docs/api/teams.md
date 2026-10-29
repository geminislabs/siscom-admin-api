# API de Teams y Members

## Descripcion

Este modulo administra equipos, membresias, reglas de visibilidad, invitaciones y eventos de emergencia.

## Autenticacion

- Endpoints bajo `/api/v1/teams/*`: JWT Bearer requerido.
- Endpoints publicos de invitacion:
  - `GET /api/v1/invites/{token}` no requiere JWT.
  - `POST /api/v1/invites/{token}/accept` requiere JWT.
- Endpoints internos (`/api/v1/internal/teams/*`): token interno (dependencia `get_auth_for_gac_admin`).

## Formato de respuesta

Todos los endpoints del modulo responden con envelope:

```json
{
  "data": {},
  "meta": {}
}
```

`meta` solo aparece en listados paginados.

## Enums

### Team type

- `FAMILY`
- `WORKFORCE`
- `FRIENDS`
- `EMERGENCY`
- `TEMPORARY`
- `TRAVEL`
- `EVENT`

### Team status

- `ACTIVE`
- `SUSPENDED`
- `EXPIRED`
- `DELETED`

### Team role

- `OWNER`
- `ADMIN`
- `MEMBER`
- `DEPENDENT`
- `EMPLOYEE`
- `VIEWER`
- `EMERGENCY_CONTACT`
- `GUEST`

### Visibility access_mode

- `ALWAYS`
- `SCHEDULED`
- `ON_DEMAND`
- `EMERGENCY_ONLY`

### Invite method

- `QR`
- `LINK`
- `EMAIL`
- `PHONE`

### Emergency type

- `SOS`
- `PANIC`
- `ACCIDENT`
- `MEDICAL`
- `OTHER`

### Emergency status

- `ACTIVE`
- `RESOLVED`
- `CANCELLED`

## Teams

### POST /api/v1/teams

Crea un team y agrega automaticamente al creador como `OWNER`.

Request:

```json
{
  "name": "Familia Cabrera",
  "type": "FAMILY",
  "timezone": "America/Mexico_City",
  "expires_at": null,
  "auto_delete_at": null,
  "metadata": {}
}
```

Reglas:

- `type` debe ser enum valido.
- `timezone` debe ser IANA valida.
- `expires_at` y `auto_delete_at` deben ser futuras.
- Si ambas fechas existen, `auto_delete_at > expires_at`.

### GET /api/v1/teams

Lista teams donde el usuario autenticado es miembro.

Query params:

- `status` (opcional)
- `type` (opcional)
- `include_deleted` (default `false`)
- `page` (default `1`, min `1`)
- `page_size` (default `50`, min `1`, max `100`)

Response (resumen):

```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Familia Cabrera",
      "type": "FAMILY",
      "status": "ACTIVE",
      "timezone": "UTC",
      "expires_at": null,
      "my_role": "OWNER",
      "member_count": 3
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 50,
    "total": 1
  }
}
```

### GET /api/v1/teams/{team_id}

Retorna detalle de team, miembros y reglas activas.

Permiso: miembro del team.

### PATCH /api/v1/teams/{team_id}

Actualiza `name`, `timezone`, `expires_at`, `auto_delete_at`, `metadata`.

Permiso: `OWNER` o `ADMIN`.

Reglas:

- No se permite actualizar si el team esta `DELETED`.
- Validaciones de fechas aplican igual que en create.

### POST /api/v1/teams/{team_id}/suspend

Permiso: `OWNER` o `ADMIN`.

### POST /api/v1/teams/{team_id}/activate

Permiso: `OWNER` o `ADMIN`.

Request opcional:

```json
{
  "expires_at": "2027-12-31T23:59:59Z"
}
```

Reglas:

- No activa si el team esta `DELETED`.
- Si `expires_at` esta en el pasado, responde conflicto.

### POST /api/v1/teams/{team_id}/expire

Permiso: `OWNER` o `ADMIN`.

Regla: solo expira si status es `ACTIVE` y `expires_at <= now`.

### DELETE /api/v1/teams/{team_id}

Permiso: `OWNER`.

Realiza eliminacion logica (`status = DELETED`).

## Members

### GET /api/v1/teams/{team_id}/members

Permiso: miembro del team.

Response:

```json
{
  "data": [
    {
      "id": "uuid",
      "team_id": "uuid",
      "user_id": "uuid",
      "display_name": "María Cabrera",
      "role": "MEMBER",
      "joined_at": "2026-08-03T18:20:00Z",
      "metadata": {}
    }
  ]
}
```

`display_name` (el `full_name` del usuario) se resuelve con una sola consulta por listado
(`WHERE id IN (...)`), sin N+1. Es **nullable**: si el usuario referenciado ya no existe llega
como `null` — los clientes no deben asumir que hay nombre, y **nunca** deben mostrar el
`user_id` como sustituto. El endpoint no expone el email del miembro.

Este mismo objeto es el que devuelven `POST /members` y `PATCH /members/{member_id}`.

### POST /api/v1/teams/{team_id}/members

Permiso: `OWNER` o `ADMIN`.

Request:

```json
{
  "user_id": "uuid",
  "role": "MEMBER",
  "metadata": {}
}
```

Reglas:

- Team debe estar `ACTIVE`.
- `ADMIN` no puede crear `OWNER`.
- `user_id` debe existir y no estar ya en el team.

### PATCH /api/v1/teams/{team_id}/members/{member_id}

Permiso: `OWNER` o `ADMIN`.

Reglas:

- `ADMIN` no puede promover/degradar `OWNER`.
- No se puede degradar al ultimo `OWNER`.

### DELETE /api/v1/teams/{team_id}/members/{member_id}

Reglas:

- `OWNER` puede remover, excepto al ultimo `OWNER`.
- `ADMIN` solo puede remover roles no administrativos.
- Un usuario puede intentar salirse, pero no si es ultimo `OWNER`.

### GET /api/v1/teams/{team_id}/me

Retorna rol y permisos efectivos del usuario dentro del team.

## Visibility Rules

### GET /api/v1/teams/{team_id}/visibility-rules

Permiso: miembro del team.

### POST /api/v1/teams/{team_id}/visibility-rules

Permiso: `OWNER` o `ADMIN`.

Request:

```json
{
  "subject_role": "EMPLOYEE",
  "viewer_role": "ADMIN",
  "access_mode": "SCHEDULED",
  "schedule": {
    "timezone": "America/Mexico_City",
    "windows": [
      {
        "days": ["MON", "TUE", "WED", "THU", "FRI"],
        "start": "08:00",
        "end": "18:00"
      }
    ]
  },
  "is_active": true,
  "metadata": {}
}
```

Reglas de schedule:

- Si `access_mode = SCHEDULED`, `schedule` es obligatorio.
- `timezone` valida IANA.
- `windows` no vacio.
- `days` en `MON..SUN`.
- `start` y `end` con formato `HH:mm`.

### PATCH /api/v1/teams/{team_id}/visibility-rules/{rule_id}

Permiso: `OWNER` o `ADMIN`.

### POST /api/v1/teams/{team_id}/visibility-rules/{rule_id}/activate

Permiso: `OWNER` o `ADMIN`.

### POST /api/v1/teams/{team_id}/visibility-rules/{rule_id}/deactivate

Permiso: `OWNER` o `ADMIN`.

### DELETE /api/v1/teams/{team_id}/visibility-rules/{rule_id}

Permiso: `OWNER` o `ADMIN`.

## Invites

### POST /api/v1/teams/{team_id}/invites

Permiso: `OWNER` o `ADMIN`.

Request:

```json
{
  "invite_method": "LINK",
  "invited_role": "MEMBER",
  "expires_at": "2027-01-01T00:00:00Z",
  "max_uses": 1,
  "metadata": {}
}
```

Reglas:

- Team debe estar `ACTIVE`.
- `ADMIN` no puede invitar como `OWNER`.
- `expires_at` debe ser futura.

Response incluye `token` (solo una vez) e `invite_url`.

`invite_url` se construye en `_build_invite_url` (`app/services/team_invite_service.py`) como
`{INVITE_BASE_URL.rstrip("/")}/invite/{token}`, donde `INVITE_BASE_URL` es un ajuste
obligatorio de `app/core/config.py` (validado al arrancar como URL absoluta `http(s)` con
host; en producción `https://nexus.geminislabs.com`). Debe apuntar al dominio que sirve el
`apple-app-site-association` / `assetlinks.json` del entorno correspondiente, para que el link
abra la app en dev y staging y no solo en producción.

> **El token solo se devuelve en esta respuesta.** En BD se guarda únicamente su SHA-256,
> así que el link es irrecuperable por diseño: `GET /invites` no puede reconstruirlo.
> Los clientes deben compartirlo en el momento de crearlo; para volver a invitar, se crea
> una invitación nueva.

### GET /api/v1/teams/{team_id}/invites

Permiso: `OWNER` o `ADMIN`.

No retorna `token_hash`.

### POST /api/v1/teams/{team_id}/invites/{invite_id}/revoke

Permiso: `OWNER` o `ADMIN`.

Marca `is_active = false`.

### GET /api/v1/invites/{token}

Publico. Valida vigencia por:

- `is_active = true`
- `expires_at > now`
- `used_count < max_uses`
- team `ACTIVE`

### POST /api/v1/invites/{token}/accept

Requiere JWT.

Flujo transaccional:

1. Valida token hash y vigencia.
2. Valida team `ACTIVE`.
3. Inserta miembro con `invited_role`.
4. Incrementa `used_count`.
5. Si alcanza `max_uses`, desactiva invite.

## Emergency Events

### POST /api/v1/teams/{team_id}/emergency-events

Permiso: miembro del team con rol habilitado (`OWNER`, `ADMIN`, `MEMBER`, `DEPENDENT`, `EMPLOYEE`, `EMERGENCY_CONTACT`).

Request:

```json
{
  "emergency_type": "SOS",
  "metadata": {
    "message": "Necesito ayuda"
  }
}
```

Regla: evita multiples eventos `ACTIVE` del mismo usuario dentro del mismo team.

### GET /api/v1/teams/{team_id}/emergency-events

Permiso: miembro del team.

Query params:

- `status` (opcional)
- `page` (default `1`)
- `page_size` (default `50`, max `100`)

### POST /api/v1/teams/{team_id}/emergency-events/{event_id}/resolve

Permiso: actor del evento, `OWNER` o `ADMIN`.

### POST /api/v1/teams/{team_id}/emergency-events/{event_id}/cancel

Permiso: actor del evento, `OWNER` o `ADMIN`.

## Internal Snapshot

### GET /api/v1/internal/teams/snapshot

Query params opcionales:

- `updated_after` (datetime)
- `account_id` (uuid)

### GET /api/v1/internal/teams/{team_id}/snapshot

Retorna snapshot de team, miembros, reglas y eventos activos.

## Eventos Kafka

Operaciones mutantes publican en `team-rules-updates` con `team_id` como key.

Eventos emitidos por la implementacion actual:

- `TEAM_CREATED`
- `TEAM_UPDATED`
- `TEAM_SUSPENDED`
- `TEAM_ACTIVATED`
- `TEAM_EXPIRED`
- `TEAM_DELETED`
- `TEAM_MEMBER_ADDED`
- `TEAM_MEMBER_UPDATED`
- `TEAM_MEMBER_REMOVED`
- `VISIBILITY_RULE_CREATED`
- `VISIBILITY_RULE_UPDATED`
- `VISIBILITY_RULE_ACTIVATED`
- `VISIBILITY_RULE_DEACTIVATED`
- `VISIBILITY_RULE_DELETED`
- `TEAM_INVITE_CREATED`
- `TEAM_INVITE_REVOKED`
- `TEAM_INVITE_ACCEPTED`
- `EMERGENCY_STARTED`
- `EMERGENCY_RESOLVED`
- `EMERGENCY_CANCELLED`

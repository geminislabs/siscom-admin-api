# Suspensión de organizaciones y cuentas

Qué pasa cuando una organización deja de dar servicio, cómo lo ven los clientes
(web, iOS, Android) y cómo lo maneja GAC. El código está en
`app/services/suspension.py` (la regla) y `app/api/deps.py` (dónde se aplica).

---

## La regla

Una organización está **suspendida** si lo está ella (`organizations.status`)
**o** la cuenta a la que pertenece (`accounts.status`). La cuenta es la raíz de
facturación: suspenderla apaga todas sus organizaciones.

| Escenario | Resultado |
|-----------|-----------|
| Se suspende la cuenta de facturación | Todas sus organizaciones quedan suspendidas |
| Una persona de esa cuenta está invitada a una organización **de otra cuenta** | Sigue entrando a la otra organización; a las suyas, no |
| Un invitado de fuera actúa en una organización suspendida | No entra a esa; a las suyas, sí |
| Se suspende una marca (`RESELLER`) | Sus clientes **no** se suspenden. GAC puede suspenderlos también, pero tiene que pedirlo (`include_subaccounts`) |
| La organización o la cuenta está `DELETED` | No entra nadie, y facturación tampoco queda abierta |

La regla mira **la organización en la que se actúa**: la de `X-Organization-Id`
si el cliente la manda, o la organización por defecto si no. La membresía se
valida antes: a quien no es miembro se le contesta el 403 de siempre, sin
contarle el estado de una organización ajena.

---

## Qué ve el cliente

### El 403

Cualquier endpoint que lea o escriba datos de la organización responde:

```http
HTTP/1.1 403 Forbidden
Content-Type: application/json

{
  "detail": "El servicio de esta organización está suspendido",
  "error_code": "organization_suspended",
  "organization_id": "223e4567-e89b-12d3-a456-426614174001",
  "suspended_by": "account",
  "can_manage_billing": true
}
```

| Campo | Valores | Significado |
|-------|---------|-------------|
| `detail` | texto | Mensaje traducido (`Accept-Language`). Sigue siendo texto para que los clientes ya publicados lo muestren como siempre |
| `error_code` | `organization_suspended` · `organization_deleted` | Lo que el cliente debe mirar para decidir qué pantalla mostrar |
| `organization_id` | UUID | La organización bloqueada |
| `suspended_by` | `organization` · `account` | Si se suspendió la organización misma o su cuenta de facturación |
| `can_manage_billing` | bool | Si esta persona puede abrir facturación para pagar y reactivarla: `owner` o `billing`, y sólo si está suspendida (nunca si está borrada) |

El cuerpo va plano, como el 426 de la [política de versiones](./client-version-policy.md), no
dentro de `detail`.

**Un 403 con `error_code` no es un fallo de credencial.** El cliente no debe
cerrar sesión ni pedir un token nuevo: debe mostrar la pantalla de suspensión.

### `GET /auth/me`

Contesta **200** aunque la organización esté suspendida o borrada, para que el
cliente se entere al arrancar sin tener que provocar un 403. El campo nuevo es
`access_blocked`:

```json
{
  "account": { "...": "..." },
  "role": "owner",
  "organization_id": "223e4567-e89b-12d3-a456-426614174001",
  "access_blocked": {
    "error_code": "organization_suspended",
    "suspended_by": "account",
    "can_manage_billing": true
  }
}
```

`access_blocked` es `null` cuando la organización da acceso.

### `GET /auth/organizations`

Cada fila trae el mismo `access_blocked`. El selector de cuenta sigue
listando las organizaciones bloqueadas, para que se vea el motivo, y puede
ofrecer cambiar a otra.

### Login

El login funciona igual, pero si la organización por defecto está bloqueada
`data_token` viene `null`: sin acceso a los datos, el cliente muestra la
pantalla de suspensión (o el selector, si la persona tiene otra organización).

### Lo que sigue abierto en una organización suspendida

| Para quién | Endpoints |
|------------|-----------|
| Todos los miembros | `GET /auth/me`, `GET /auth/organizations`, `GET /users/me`, `POST /auth/logout`, `PATCH /auth/password`, `POST /auth/refresh`, `/mobility/devices/*` (el registro del teléfono para push es de la persona, no de la organización) |
| `owner` y `billing` | `/billing/*`, `/stripe/*`, `/payments`, `GET /subscriptions*`, `POST /subscriptions/{id}/cancel`, `PATCH /subscriptions/{id}/auto-renew` |

En una organización **borrada** sólo queda lo de la primera fila.

Todo lo comercial de una cuenta suspendida o borrada (`/accounts/{id}/branding/*`)
también queda cerrado, con un 403 sin `error_code`.

### La pantalla de suspensión (para la 1.3.0)

- `can_manage_billing: true` → mensaje y botón **«Ir a facturación»**.
- `can_manage_billing: false` → mensaje «Contacta al administrador de tu cuenta».
- `organization_deleted` → mensaje sin botón de facturación.
- Si `GET /auth/organizations` trae otra organización con `access_blocked: null`,
  ofrecer **«Cambiar de organización»**.
- Siempre **«Cerrar sesión»**.

---

## Revocación

Al confirmar el cambio de estado, el ORM (`app/services/session_revocation.py`)
revoca:

- los data tokens de sesión de **todos** los miembros activos de las
  organizaciones afectadas;
- los **enlaces compartidos** de todas sus unidades.

Reactivar no revoca nada; los clientes vuelven a pedir su data token. Los
enlaces compartidos que se apagaron no vuelven: hay que compartir de nuevo.

> **Límite actual:** mientras `DATA_TOKEN_ENFORCED=false` en siscom-api, el plano
> de datos sigue aceptando peticiones sin data token, así que revocar no corta
> por sí solo la lectura de posiciones. Lo cierra D3. Las alertas push
> (alert-distributor) tampoco miran todavía el estado de la organización.

---

## GAC

### `GET /api/v1/internal/accounts/{account_id}/subaccounts`

Las subcuentas de una cuenta en todo su árbol, sin incluirla a ella, ordenadas
por nombre. Es lo que GAC muestra antes de suspender o reactivar una marca con
`include_subaccounts`.

```json
[
  {
    "id": "…",
    "account_name": "Cliente de la marca",
    "status": "ACTIVE",
    "account_type": "CUSTOMER",
    "parent_account_id": "…"
  }
]
```

404 si la cuenta no existe.

### `PATCH /api/v1/internal/accounts/{account_id}/status`

Auth: PASETO `service=gac`, `role=GAC_ADMIN`.

```json
{
  "status": "SUSPENDED",
  "include_subaccounts": false,
  "reason": "Falta de pago de octubre"
}
```

| Campo | Tipo | Notas |
|-------|------|-------|
| `status` | `ACTIVE` · `SUSPENDED` | Borrar no se hace aquí (`DELETED` → 422) |
| `include_subaccounts` | bool, opcional (`false`) | Sólo para una cuenta `RESELLER` (otra → 422). Aplica el cambio a todo su árbol. Al reactivar, reactiva también las subcuentas que estuvieran suspendidas por su cuenta: enseñar la lista antes de confirmar |
| `reason` | string ≤ 500, opcional | Va a la auditoría |

**200:**

```json
{
  "account": {
    "id": "…",
    "account_name": "Transportes García",
    "previous_status": "ACTIVE",
    "status": "SUSPENDED"
  },
  "changed": true,
  "subaccounts": []
}
```

- `changed: false` si la cuenta ya tenía ese estado. No es un error, y con
  `include_subaccounts` las subcuentas se procesan igual.
- `subaccounts` trae sólo las que cambiaron de verdad. Las borradas, o las que
  ya tenían ese estado, se saltan.

| Código | Cuándo |
|--------|--------|
| 404 | La cuenta no existe |
| 409 | La cuenta está `DELETED` |
| 422 | `status` inválido, o `include_subaccounts` en una cuenta que no es `RESELLER` |

Cada cuenta que cambia deja un `account_events` con
`event_type = account_status_changed` y, en `metadata`: `anterior`, `nuevo`,
`reason`, `via_reseller` (la marca, si llegó por ella), `service` y `gac_user`.

### Suspender una sola organización

Sigue siendo `PATCH /api/v1/internal/organizations/{id}/status?new_status=SUSPENDED`
(ver [internal-organizations.md](./internal-organizations.md)). Desde esta
versión ese cambio también cierra el acceso y revoca.

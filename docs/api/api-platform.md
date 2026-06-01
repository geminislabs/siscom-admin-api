# API Platform

## Descripción

Módulo de gestión de API keys, métricas de uso, logs de solicitudes y alertas operativas.

Permite a las organizaciones crear y administrar sus propias API keys para integraciones externas, monitorear el consumo en tiempo real, y configurar alertas sobre tasas de error o umbrales de uso.

Todas las operaciones usan el contexto del usuario autenticado. El `organization_id` se deriva automáticamente del token JWT — **no debe enviarse en el body**.

**Base URL:** `/api/v1/api-platform`

---

## Modelo de Datos

### ApiKey

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "product_id": "550e8400-e29b-41d4-a716-446655440002",
  "name": "backend-produccion",
  "prefix": "orion_live_AbCdEfGh",
  "status": "ACTIVE",
  "created_at": "2026-05-01T10:00:00Z",
  "last_used_at": "2026-05-01T12:30:00Z",
  "expires_at": null,
  "revoked_at": null,
  "key_metadata": {
    "environment": "production",
    "team": "backend"
  }
}
```

> **Nota de seguridad:** el campo `full_key` (clave en texto plano) se devuelve **una sola vez** al crear la key. El backend almacena únicamente el hash SHA-256. Si se pierde la clave, debe generarse una nueva.

### UsageSummary

```json
{
  "active_keys": 3,
  "requests_today": 12540,
  "requests_month": 284300,
  "error_rate": 0.0042
}
```

### LogEntry

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "api_key_id": "550e8400-e29b-41d4-a716-446655440000",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "method": "GET",
  "endpoint": "/v1/locate",
  "status_code": 200,
  "latency_ms": 48,
  "ip": "203.0.113.45",
  "user_agent": "MyApp/2.1.0",
  "request_size": 142,
  "response_size": 890,
  "error_code": null,
  "created_at": "2026-05-01T12:30:00.123Z"
}
```

### ApiAlert

```json
{
  "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "api_key_id": null,
  "type": "ERROR_RATE",
  "threshold": 0.05,
  "time_window": "5m",
  "enabled": true,
  "created_at": "2026-05-01T10:00:00Z"
}
```

---

## Reglas de Negocio

| Regla | Comportamiento |
|-------|----------------|
| Aislamiento de tenant | Todas las operaciones están filtradas por `organization_id` del token |
| Clave en texto plano | `full_key` solo se retorna en la respuesta de creación (`POST /keys`); jamás en consultas posteriores |
| Hash de clave | El backend almacena `SHA-256(full_key)`. No es reversible |
| Prefijo de referencia | `prefix` es los primeros 20 caracteres de `full_key` (ej: `orion_live_AbCdEfGh`); sirve para identificar visualmente la clave sin exponerla |
| Revocación | `POST /keys/{id}/revoke` establece `status=REVOKED` y `revoked_at=now()`. Una key ya revocada responde `409` |
| Paginación de logs | Cursor-based usando `(created_at DESC, id DESC)`. El cursor es opaco (base64url). No usar offset |
| Dashboard de uso | Los endpoints `/usage/*` consultan las tablas de agregados (`api_usage_daily`, `api_usage_monthly`, `api_usage_counters`), nunca los logs crudos |
| Límites de plan | `/usage/limits` resuelve el `plan_id` de la suscripción activa para obtener los límites configurados en `api_limits` |

---

## Endpoints

---

## 1. API Keys

### Crear API Key

**POST** `/api/v1/api-platform/keys`

Genera una nueva clave segura. La clave en texto plano se retorna **una sola vez** en el campo `full_key`.

#### Headers

```text
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request Body

```json
{
  "product_code": "orion",
  "name": "backend-produccion",
  "expires_at": null,
  "key_metadata": {
    "environment": "production",
    "team": "backend"
  }
}
```

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `product_code` | string | Sí | Código único del producto (ej: `orion`) |
| `name` | string | Sí | Nombre descriptivo (1-100 caracteres) |
| `expires_at` | datetime ISO 8601 | No | Fecha de expiración opcional |
| `key_metadata` | object | No | Metadatos arbitrarios en JSON |

#### Response `201 Created`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "product_id": "550e8400-e29b-41d4-a716-446655440002",
  "name": "backend-produccion",
  "prefix": "orion_live_AbCdEfGh",
  "status": "ACTIVE",
  "created_at": "2026-05-01T10:00:00Z",
  "last_used_at": null,
  "expires_at": null,
  "revoked_at": null,
  "key_metadata": {
    "environment": "production",
    "team": "backend"
  },
  "full_key": "orion_live_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_abc"
}
```

> **Importante:** guarda `full_key` de inmediato. No volverá a mostrarse.

#### Response `404 Not Found`

```json
{
  "error": "product_not_found",
  "message": "The specified product does not exist or is not available."
}
```

---

### Listar API Keys

**GET** `/api/v1/api-platform/keys`

Retorna únicamente las API keys de la organización del usuario autenticado. El `organization_id` se extrae automáticamente del token JWT. Requiere `Authorization: Bearer <access_token>`.

#### Query Parameters

| Parámetro      | Tipo   | Descripción                                   |
|----------------|--------|-----------------------------------------------|
| `status`       | string | `ACTIVE`, `REVOKED` o `EXPIRED`               |
| `product_code` | string | Filtra por código de producto (ej: `orion`)   |

#### Response `200 OK`

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "organization_id": "550e8400-e29b-41d4-a716-446655440001",
    "product_id": "550e8400-e29b-41d4-a716-446655440002",
    "name": "backend-produccion",
    "prefix": "orion_live_AbCdEfGh",
    "status": "ACTIVE",
    "created_at": "2026-05-01T10:00:00Z",
    "last_used_at": "2026-05-01T12:30:00Z",
    "expires_at": null,
    "revoked_at": null,
    "key_metadata": {}
  }
]
```

---

### Obtener API Key

**GET** `/api/v1/api-platform/keys/{key_id}`

#### Response `200 OK`

Devuelve un objeto `ApiKey` (sin `full_key`).

#### Errores

- `404 Not Found`: la key no existe o no pertenece a la organización

---

### Revocar API Key

**POST** `/api/v1/api-platform/keys/{key_id}/revoke`

Establece `status=REVOKED` y registra el timestamp de revocación. Esta acción es irreversible.

#### Response `200 OK`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "REVOKED",
  "revoked_at": "2026-05-01T15:00:00Z",
  "...": "..."
}
```

#### Response `409 Conflict`

```json
{
  "detail": "API key is already revoked"
}
```

---

### Actualizar API Key

**PATCH** `/api/v1/api-platform/keys/{key_id}`

Permite actualizar `name` y/o `status`. Todos los campos son opcionales.

#### Request Body

```json
{
  "name": "backend-produccion-v2",
  "status": "ACTIVE"
}
```

| Campo | Tipo | Valores válidos |
|-------|------|-----------------|
| `name` | string | 1-100 caracteres |
| `status` | string | `ACTIVE`, `REVOKED`, `EXPIRED` |

#### Response `200 OK`

Devuelve el objeto `ApiKey` actualizado.

---

## 2. Uso (Dashboard)

### Resumen de Uso

**GET** `/api/v1/api-platform/usage/summary`

Retorna métricas agregadas de la organización para hoy y el mes actual.

#### Response `200 OK`

```json
{
  "active_keys": 3,
  "requests_today": 12540,
  "requests_month": 284300,
  "error_rate": 0.0042
}
```

| Campo | Descripción |
|-------|-------------|
| `active_keys` | Keys con `status=ACTIVE` |
| `requests_today` | Suma de `request_count` en `api_usage_daily` para hoy |
| `requests_month` | Suma de `request_count` en `api_usage_monthly` para el mes actual |
| `error_rate` | `errors_today / requests_today`; `0.0` si no hay solicitudes |

---

### Uso por Key

**GET** `/api/v1/api-platform/usage/by-key`

Desglose del tráfico de hoy por cada API key, con su porcentaje relativo.

#### Response `200 OK`

```json
[
  {
    "api_key_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "backend-produccion",
    "requests": 8200,
    "percentage": 65.4
  },
  {
    "api_key_id": "550e8400-e29b-41d4-a716-446655440003",
    "name": "mobile-app",
    "requests": 4340,
    "percentage": 34.6
  }
]
```

---

### Serie de Tiempo

**GET** `/api/v1/api-platform/usage/timeseries`

Retorna solicitudes y errores agrupados por granularidad temporal.

#### Query Parameters

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `from` | datetime ISO 8601 | Sí | Inicio del rango |
| `to` | datetime ISO 8601 | Sí | Fin del rango |
| `granularity` | string | No | `minute`, `day` (default), `month` |
| `api_key_id` | UUID | No | Filtra por una key específica |

> `from` debe ser anterior a `to`, de lo contrario responde `400 Bad Request`.

#### Response `200 OK`

```json
[
  {
    "bucket": "2026-05-01T00:00:00",
    "request_count": 4820,
    "error_count": 20
  },
  {
    "bucket": "2026-04-30T00:00:00",
    "request_count": 5100,
    "error_count": 18
  }
]
```

**Ejemplo con granularidad minuto** (`granularity=minute`):

```json
[
  {
    "bucket": "2026-05-01T12:00:00Z",
    "request_count": 142,
    "error_count": 1
  },
  {
    "bucket": "2026-05-01T12:01:00Z",
    "request_count": 138,
    "error_count": 0
  }
]
```

---

### Estado de Límites

**GET** `/api/v1/api-platform/usage/limits`

Compara los límites configurados en el plan de la organización contra el consumo actual.

#### Response `200 OK`

```json
{
  "rpm_limit": 1000,
  "rpm_current": 342,
  "daily_limit": 100000,
  "daily_current": 12540,
  "monthly_limit": 2000000,
  "monthly_current": 284300,
  "burst_limit": 50,
  "burst_current": null
}
```

> Los campos `*_limit` son `null` si la organización no tiene suscripción activa o si el plan no define ese límite.

---

## 3. Logs

### Listar Logs

**GET** `/api/v1/api-platform/logs`

Paginación cursor-based. Cada página devuelve hasta `limit` registros ordenados por `created_at DESC`.

#### Query Parameters

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `cursor` | string | — | Cursor opaco de la página anterior |
| `limit` | integer | 50 | Máximo 200 |
| `api_key_id` | UUID | — | Filtra por key |
| `status_code` | integer | — | Ej: `200`, `429`, `500` |
| `method` | string | — | `GET`, `POST`, etc. |
| `endpoint` | string | — | Búsqueda parcial en la ruta |
| `from` | datetime ISO 8601 | — | `created_at >= from` |
| `to` | datetime ISO 8601 | — | `created_at <= to` |
| `ip` | string | — | IP exacta |

#### Response `200 OK`

```json
{
  "items": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "api_key_id": "550e8400-e29b-41d4-a716-446655440000",
      "organization_id": "550e8400-e29b-41d4-a716-446655440001",
      "method": "GET",
      "endpoint": "/v1/locate",
      "status_code": 200,
      "latency_ms": 48,
      "ip": "203.0.113.45",
      "user_agent": "MyApp/2.1.0",
      "request_size": 142,
      "response_size": 890,
      "error_code": null,
      "created_at": "2026-05-01T12:30:00.123Z"
    }
  ],
  "next_cursor": "MjAyNi0wNS0wMVQxMjoyOTowMC4wMDBafGExYjJjM2Q0LWU1ZjYtNzg5MC1hYmNkLWVmMTIzNDU2Nzg5MA==",
  "limit": 50
}
```

#### Cómo usar la paginación

```text
# Primera página
GET /api/v1/api-platform/logs?limit=50

# Siguiente página
GET /api/v1/api-platform/logs?limit=50&cursor=<next_cursor de la respuesta anterior>
```

> Si `next_cursor` es `null`, no hay más registros.

---

### Estadísticas de Logs

**GET** `/api/v1/api-platform/logs/stats`

Métricas calculadas sobre las solicitudes del día y las últimas 24 horas.

#### Response `200 OK`

```json
{
  "requests_today": 12540,
  "success_rate": 0.9958,
  "p50_latency_ms": 62.5,
  "errors_24h": 53
}
```

| Campo | Descripción |
|-------|-------------|
| `requests_today` | Total de solicitudes desde las 00:00 UTC de hoy |
| `success_rate` | `requests_2xx / total_today`; `1.0` si no hay solicitudes |
| `p50_latency_ms` | Percentil 50 de `latency_ms` del día; `null` si no hay datos |
| `errors_24h` | Solicitudes con `status_code >= 400` en las últimas 24 horas |

---

## 4. Eventos de Throttle

**GET** `/api/v1/api-platform/throttles`

Lista los eventos de throttling (límite de tasa alcanzado) de la organización.

#### Query Parameters

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `type` | string | `RPM_LIMIT`, `DAILY_LIMIT` o `BURST` |
| `from` | datetime ISO 8601 | Inicio del rango |
| `to` | datetime ISO 8601 | Fin del rango |
| `limit` | integer | Default 100, máximo 500 |
| `offset` | integer | Default 0 |

#### Response `200 OK`

```json
[
  {
    "id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
    "api_key_id": "550e8400-e29b-41d4-a716-446655440000",
    "organization_id": "550e8400-e29b-41d4-a716-446655440001",
    "type": "RPM_LIMIT",
    "limit_value": 1000,
    "actual_value": 1043,
    "created_at": "2026-05-01T12:31:00Z"
  }
]
```

| Campo | Descripción |
|-------|-------------|
| `type` | Tipo de límite alcanzado |
| `limit_value` | Límite configurado |
| `actual_value` | Valor real que desencadenó el throttle |

---

## 5. Alertas

### Crear Alerta

**POST** `/api/v1/api-platform/alerts`

#### Request Body

```json
{
  "type": "ERROR_RATE",
  "threshold": 0.05,
  "time_window": "5m",
  "api_key_id": null
}
```

| Campo | Tipo | Requerido | Descripción |
|-------|------|-----------|-------------|
| `type` | string | Sí | `ERROR_RATE` o `USAGE_THRESHOLD` |
| `threshold` | number | No | Valor numérico del umbral (ej: `0.05` para 5%) |
| `time_window` | string | No | Ventana de tiempo (ej: `"5m"`, `"1h"`) |
| `api_key_id` | UUID | No | `null` = aplica a toda la organización |

#### Response `201 Created`

```json
{
  "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "api_key_id": null,
  "type": "ERROR_RATE",
  "threshold": 0.05,
  "time_window": "5m",
  "enabled": true,
  "created_at": "2026-05-01T10:00:00Z"
}
```

---

### Listar Alertas

**GET** `/api/v1/api-platform/alerts`

#### Response `200 OK`

```json
[
  {
    "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
    "organization_id": "550e8400-e29b-41d4-a716-446655440001",
    "api_key_id": null,
    "type": "ERROR_RATE",
    "threshold": 0.05,
    "time_window": "5m",
    "enabled": true,
    "created_at": "2026-05-01T10:00:00Z"
  },
  {
    "id": "d4e5f6a7-b8c9-0123-defa-234567890123",
    "organization_id": "550e8400-e29b-41d4-a716-446655440001",
    "api_key_id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "USAGE_THRESHOLD",
    "threshold": 90000,
    "time_window": "1h",
    "enabled": false,
    "created_at": "2026-04-28T09:00:00Z"
  }
]
```

---

### Activar / Desactivar Alerta

**PATCH** `/api/v1/api-platform/alerts/{alert_id}`

#### Request Body

```json
{
  "enabled": false
}
```

#### Response `200 OK`

Devuelve el objeto `ApiAlert` actualizado.

#### Errores

- `404 Not Found`: la alerta no existe o no pertenece a la organización

---

## Errores Frecuentes

| Código | Caso |
|--------|------|
| `400 Bad Request` | Parámetro inválido (ej: `from >= to` en timeseries, `status` fuera de rango) |
| `401 Unauthorized` | Token ausente o expirado |
| `404 Not Found` | Recurso no encontrado o no pertenece a la organización |
| `409 Conflict` | Intentar revocar una key ya revocada |

---

## Ejemplos de Uso con cURL

### Crear una API Key

```bash
curl -X POST "http://localhost:8000/api/v1/api-platform/keys" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": "550e8400-e29b-41d4-a716-446655440002",
    "name": "backend-produccion",
    "key_metadata": {
      "environment": "production"
    }
  }'
```

### Listar Keys activas de un producto

```bash
curl -X GET "http://localhost:8000/api/v1/api-platform/keys?status=ACTIVE&product_id=550e8400-e29b-41d4-a716-446655440002" \
  -H "Authorization: Bearer <token>"
```

### Revocar una Key

```bash
curl -X POST "http://localhost:8000/api/v1/api-platform/keys/550e8400-e29b-41d4-a716-446655440000/revoke" \
  -H "Authorization: Bearer <token>"
```

### Ver resumen de uso del día

```bash
curl -X GET "http://localhost:8000/api/v1/api-platform/usage/summary" \
  -H "Authorization: Bearer <token>"
```

### Serie de tiempo de la última semana (granularidad día)

```bash
curl -X GET "http://localhost:8000/api/v1/api-platform/usage/timeseries?from=2026-04-24T00:00:00Z&to=2026-05-01T23:59:59Z&granularity=day" \
  -H "Authorization: Bearer <token>"
```

### Serie de tiempo de la última hora (granularidad minuto) para una key específica

```bash
curl -X GET "http://localhost:8000/api/v1/api-platform/usage/timeseries?from=2026-05-01T11:00:00Z&to=2026-05-01T12:00:00Z&granularity=minute&api_key_id=550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer <token>"
```

### Ver estado de límites del plan

```bash
curl -X GET "http://localhost:8000/api/v1/api-platform/usage/limits" \
  -H "Authorization: Bearer <token>"
```

### Consultar logs con filtros

```bash
curl -X GET "http://localhost:8000/api/v1/api-platform/logs?status_code=500&from=2026-05-01T00:00:00Z&to=2026-05-01T23:59:59Z&limit=100" \
  -H "Authorization: Bearer <token>"
```

### Navegar a la siguiente página de logs con cursor

```bash
# Primera página
RESPONSE=$(curl -s "http://localhost:8000/api/v1/api-platform/logs?limit=50" \
  -H "Authorization: Bearer <token>")

CURSOR=$(echo $RESPONSE | jq -r '.next_cursor')

# Segunda página
curl -X GET "http://localhost:8000/api/v1/api-platform/logs?limit=50&cursor=${CURSOR}" \
  -H "Authorization: Bearer <token>"
```

### Ver estadísticas de logs

```bash
curl -X GET "http://localhost:8000/api/v1/api-platform/logs/stats" \
  -H "Authorization: Bearer <token>"
```

### Consultar eventos de throttle del tipo RPM del último día

```bash
curl -X GET "http://localhost:8000/api/v1/api-platform/throttles?type=RPM_LIMIT&from=2026-05-01T00:00:00Z&to=2026-05-01T23:59:59Z" \
  -H "Authorization: Bearer <token>"
```

### Crear alerta de tasa de error global

```bash
curl -X POST "http://localhost:8000/api/v1/api-platform/alerts" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "ERROR_RATE",
    "threshold": 0.05,
    "time_window": "5m"
  }'
```

### Crear alerta de uso por key específica

```bash
curl -X POST "http://localhost:8000/api/v1/api-platform/alerts" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "USAGE_THRESHOLD",
    "threshold": 90000,
    "time_window": "1h",
    "api_key_id": "550e8400-e29b-41d4-a716-446655440000"
  }'
```

### Desactivar una alerta

```bash
curl -X PATCH "http://localhost:8000/api/v1/api-platform/alerts/b2c3d4e5-f6a7-8901-bcde-f12345678901" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

---

**Última actualización**: 1 de mayo de 2026  
**Referencia**: [Índice de APIs](./INDEX.md) | [Autenticación](./authentication.md)

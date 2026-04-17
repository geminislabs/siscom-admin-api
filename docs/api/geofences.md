# API de Geocercas (Geofences)

## Descripción

Endpoints para gestionar geocercas por organización usando índices H3.

El frontend y sistemas externos envían los índices H3 ya calculados; esta API se encarga del CRUD y de la persistencia en:

- `geofences`
- `geofence_cells`

Todas las operaciones usan el contexto del usuario autenticado. El cliente no debe enviar `organization_id` ni `created_by`.

---

## Modelo de Datos

### Geofence

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "created_by": "550e8400-e29b-41d4-a716-446655440002",
  "name": "Bodega Norte",
  "description": "Perimetro zona de carga",
  "config": {
    "color": "#2E86DE",
    "category": "logistica"
  },
  "h3_indexes": [
    617733123456789503,
    617733123456789504,
    617733123456789505
  ],
  "is_active": true,
  "created_at": "2026-04-06T12:00:00Z",
  "updated_at": "2026-04-06T12:00:00Z"
}
```

---

## Reglas de Negocio

| Regla | Comportamiento |
| --- | --- |
| Tenant actual | Todas las consultas se filtran por la organización del usuario autenticado |
| Soft delete | `DELETE /geofences/{geofence_id}` marca `is_active=false` |
| H3 duplicados en request | Se deduplican antes de persistir |
| PATCH atómico | Si se envía `h3_indexes`, el backend borra celdas actuales e inserta las nuevas en una sola transacción |
| Timestamp de actualización | En `PATCH` y `DELETE` se actualiza `updated_at` |

### Estrategia de actualización de H3

Cuando `PATCH` recibe `h3_indexes`, se aplica esta secuencia dentro de la misma transacción:

1. Eliminar celdas actuales de la geocerca.
2. Insertar la nueva lista de índices H3.
3. Actualizar metadata (`name`, `description`, `config`, `is_active` si aplica).
4. Commit único.

Si ocurre un error de integridad, se realiza rollback completo.

---

## Endpoints

### 1. Crear Geocerca

**POST** `/api/v1/geofences`

#### Headers

```text
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request Body

```json
{
  "name": "Bodega Norte",
  "description": "Perimetro zona de carga",
  "config": {
    "color": "#2E86DE",
    "category": "logistica"
  },
  "h3_indexes": [
    617733123456789503,
    617733123456789504,
    617733123456789504
  ]
}
```

#### Response `201 Created`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "created_by": "550e8400-e29b-41d4-a716-446655440002",
  "name": "Bodega Norte",
  "description": "Perimetro zona de carga",
  "config": {
    "color": "#2E86DE",
    "category": "logistica"
  },
  "h3_indexes": [
    617733123456789503,
    617733123456789504
  ],
  "is_active": true,
  "created_at": "2026-04-06T12:00:00Z",
  "updated_at": "2026-04-06T12:00:00Z"
}
```

#### Errores comunes

- `409 Conflict`: conflicto de integridad en base de datos

---

### 2. Listar Geocercas Activas

**GET** `/api/v1/geofences`

Lista solo geocercas activas de la organización autenticada.

#### Response `200 OK`

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "organization_id": "550e8400-e29b-41d4-a716-446655440001",
    "created_by": "550e8400-e29b-41d4-a716-446655440002",
    "name": "Bodega Norte",
    "description": "Perimetro zona de carga",
    "config": {
      "color": "#2E86DE",
      "category": "logistica"
    },
    "h3_indexes": [
      617733123456789503,
      617733123456789504
    ],
    "is_active": true,
    "created_at": "2026-04-06T12:00:00Z",
    "updated_at": "2026-04-06T12:00:00Z"
  }
]
```

---

### 3. Obtener Geocerca por ID

**GET** `/api/v1/geofences/{geofence_id}`

Obtiene una geocerca activa de la organización autenticada.

#### Errores comunes

- `404 Not Found`: geocerca inexistente, inactiva o de otra organización

---

### 4. Actualizar Geocerca

**PATCH** `/api/v1/geofences/{geofence_id}`

Todos los campos son opcionales. Solo se actualizan los enviados.

#### Request Body (metadata)

```json
{
  "name": "Bodega Norte - Actualizada",
  "description": "Perimetro final",
  "config": {
    "color": "#1B4F72",
    "category": "logistica"
  }
}
```

#### Request Body (metadata + reemplazo H3)

```json
{
  "name": "Bodega Norte - Cobertura nueva",
  "h3_indexes": [
    617733123456789600,
    617733123456789601,
    617733123456789601
  ]
}
```

#### Response `200 OK`

Devuelve el objeto `GeofenceOut` con la lista final deduplicada.

#### Errores comunes

- `404 Not Found`: geocerca inexistente, inactiva o de otra organización
- `409 Conflict`: conflicto de integridad en base de datos

---

### 5. Desactivar Geocerca

**DELETE** `/api/v1/geofences/{geofence_id}`

Realiza soft delete (`is_active=false`).

#### Response `200 OK`

```json
{
  "message": "Geocerca desactivada exitosamente",
  "geofence_id": "550e8400-e29b-41d4-a716-446655440000",
  "is_active": false
}
```

#### Errores comunes

- `404 Not Found`: geocerca inexistente, inactiva o de otra organización

---

## Ejemplos curl

### Crear

```bash
curl -X POST "http://localhost:8090/api/v1/geofences" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Planta Monterrey",
    "description": "Zona de operaciones",
    "config": {"priority": "high"},
    "h3_indexes": [617733123456789503, 617733123456789504]
  }'
```

### Actualizar reemplazando H3

```bash
curl -X PATCH "http://localhost:8090/api/v1/geofences/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Planta Monterrey v2",
    "h3_indexes": [617733123456789900, 617733123456789901]
  }'
```

### Desactivar

```bash
curl -X DELETE "http://localhost:8090/api/v1/geofences/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer <access_token>"
```

---

## Publicacion de Eventos en Kafka

Al completar exitosamente `POST`, `PATCH` o `DELETE`, la API publica un evento en el topico configurado por `KAFKA_GEOFENCES_UPDATES_TOPIC`.

Si la publicacion en Kafka falla, la operacion HTTP no falla: la persistencia en BD se mantiene y el error se registra en logs.

### Variables de entorno

```dotenv
KAFKA_BROKERS=127.0.0.1:9092
KAFKA_GEOFENCES_UPDATES_TOPIC=geofences-updates
KAFKA_SASL_USERNAME=alerts-rules-producer
KAFKA_SASL_PASSWORD=alertsrulesproducerpassword
KAFKA_SASL_MECHANISM=SCRAM-SHA-256
KAFKA_SECURITY_PROTOCOL=SASL_PLAINTEXT
```

### Mensaje de actualizacion de geocerca (PATCH -> UPSERT)

Este es el mensaje que se publica cuando una geocerca se actualiza. El payload incluye snapshot completo y `cells` siempre es obligatorio.

```json
{
  "event_id": "6c8e3c7c-1f92-4b9f-8f7a-2c9c2fbb9d1a",
  "event_type": "UPSERT",
  "entity": "geofence",
  "timestamp": "2026-04-16T18:00:00Z",
  "organization_id": "c24ba579-6a27-42d9-a398-0486fbe54f8c",
  "data": {
    "id": "geofence-uuid",
    "created_by": "user-uuid",
    "name": "Test",
    "description": "",
    "is_active": true,
    "config": {
      "color": "#2E86DE",
      "category": ""
    },
    "cells": [
      617733123123123123,
      617733123123123124,
      617733123123123125
    ],
    "updated_at": "2026-04-16T17:59:59Z"
  }
}
```

### Mensaje de eliminacion logica (DELETE)

```json
{
  "event_id": "2f91d2a0-9c7a-4f12-8a11-2d9b2b8e7c11",
  "event_type": "DELETE",
  "entity": "geofence",
  "timestamp": "2026-04-16T18:05:00Z",
  "organization_id": "c24ba579-6a27-42d9-a398-0486fbe54f8c",
  "data": {
    "id": "geofence-uuid"
  }
}
```

### Contrato del evento

- `event_type`: `UPSERT` para create/update, `DELETE` para desactivacion.
- `config`: se publica directo como JSONB, sin transformaciones.
- `cells`: obligatorio en todos los eventos `UPSERT`.
- `timestamp` y `data.updated_at`: en formato UTC con sufijo `Z`.

---

## Notas Técnicas

- El backend no calcula celdas H3; solo persiste las recibidas.
- La actualización de celdas está optimizada para velocidad mediante reemplazo total en `PATCH`.
- El trigger de base de datos para `updated_at` sigue vigente; además, el endpoint actualiza el campo explícitamente en `PATCH` y `DELETE`.
- No se requieren migraciones para este módulo.
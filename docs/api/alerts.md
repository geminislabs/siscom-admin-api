# API de Alertas

## Descripción

Endpoints para gestionar reglas de alerta por organización y consultar alertas generadas por unidad.

Todas las operaciones usan el contexto del usuario autenticado. El cliente no debe enviar `organization_id` ni `user_id` para consultar sus propias reglas o alertas.

---

## Modelo de Datos

### AlertRule

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "created_by": "550e8400-e29b-41d4-a716-446655440002",
  "name": "Regla ignicion off",
  "type": "ignition_off",
  "config": {
    "event": "Engine OFF"
  },
  "unit_ids": [
    "550e8400-e29b-41d4-a716-446655440010",
    "550e8400-e29b-41d4-a716-446655440011"
  ],
  "is_active": true,
  "created_at": "2026-04-05T10:00:00Z",
  "updated_at": "2026-04-05T10:00:00Z"
}
```

### Alert

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440100",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "rule_id": "550e8400-e29b-41d4-a716-446655440000",
  "unit_id": "550e8400-e29b-41d4-a716-446655440010",
  "source_type": "event",
  "source_id": "evt-12345",
  "type": "ignition_off",
  "payload": {
    "event": "Engine OFF",
    "speed": 0
  },
  "occurred_at": "2026-04-05T09:58:00Z",
  "created_at": "2026-04-05T09:58:01Z"
}
```

---

## Reglas de Negocio

| Regla | Comportamiento |
| --- | --- |
| Tenant actual | Todas las consultas se filtran por la organizacion del usuario autenticado |
| Organizacion inactiva | `GET /alert_rules` y `GET /alerts` responden lista vacia si la organizacion no esta activa |
| Soft delete | `DELETE /alert_rules/{rule_id}` no elimina la regla; marca `is_active=false` |
| Deduplicacion | Crear o actualizar una regla puede responder `409` si el fingerprint colisiona con otra regla activa o existente |
| Unidades validas | Los `unit_ids` deben pertenecer a la organizacion del usuario y no estar eliminados |
| Filtro por unidad en alertas | Si se envia `unit_id`, el endpoint valida acceso a esa unidad |
| Normalizacion de config | `config` se normaliza antes de persistir: elimina claves con `null` y ordena llaves de forma deterministica |

### Fingerprint de reglas

El backend genera un fingerprint SHA-256 a partir de:

```text
organization_id|type|canonical_json(config)
```

Si el fingerprint ya existe, la API responde:

```json
{
  "id": "existing_rule_id",
  "message": "Regla ya existente"
}
```

### Normalizacion de `config`

Entrada:

```json
{
  "z": 1,
  "a": {
    "k2": null,
    "k1": "ok"
  },
  "m": [
    {
      "b": 2,
      "a": 1,
      "c": null
    },
    null
  ],
  "n": null
}
```

Salida persistida:

```json
{
  "a": {
    "k1": "ok"
  },
  "m": [
    {
      "a": 1,
      "b": 2
    },
    null
  ],
  "z": 1
}
```

---

## Endpoints

### 1. Crear Regla de Alerta

**POST** `/api/v1/alert_rules`

#### Headers

```text
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request Body

```json
{
  "name": "Regla ignicion off",
  "type": "ignition_off",
  "config": {
    "event": "Engine OFF"
  },
  "unit_ids": [
    "550e8400-e29b-41d4-a716-446655440010",
    "550e8400-e29b-41d4-a716-446655440011"
  ]
}
```

#### Validaciones

- `name`: requerido, 1 a 255 caracteres
- `type`: requerido, 1 a 120 caracteres
- `config`: objeto JSON, opcionalmente vacio
- `unit_ids`: opcional; si se envian, todas las unidades deben pertenecer a la organizacion autenticada

#### Response `201 Created`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "organization_id": "550e8400-e29b-41d4-a716-446655440001",
  "created_by": "550e8400-e29b-41d4-a716-446655440002",
  "name": "Regla ignicion off",
  "type": "ignition_off",
  "config": {
    "event": "Engine OFF"
  },
  "unit_ids": [
    "550e8400-e29b-41d4-a716-446655440010",
    "550e8400-e29b-41d4-a716-446655440011"
  ],
  "is_active": true,
  "created_at": "2026-04-05T10:00:00Z",
  "updated_at": "2026-04-05T10:00:00Z"
}
```

#### Response `409 Conflict`

```json
{
  "id": "550e8400-e29b-41d4-a716-446655449999",
  "message": "Regla ya existente"
}
```

---

### 2. Listar Reglas Activas

**GET** `/api/v1/alert_rules`

Lista las reglas activas de la organizacion del usuario autenticado.

#### Query Parameters

| Parametro | Tipo | Requerido | Descripcion |
| --- | --- | --- | --- |
| `type` | string | No | Filtra por tipo exacto |
| `unit_id` | UUID | No | Filtra reglas asignadas a una unidad especifica |

#### Response `200 OK`

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "organization_id": "550e8400-e29b-41d4-a716-446655440001",
    "created_by": "550e8400-e29b-41d4-a716-446655440002",
    "name": "Regla ignicion off",
    "type": "ignition_off",
    "config": {
      "event": "Engine OFF"
    },
    "unit_ids": [
      "550e8400-e29b-41d4-a716-446655440010"
    ],
    "is_active": true,
    "created_at": "2026-04-05T10:00:00Z",
    "updated_at": "2026-04-05T10:00:00Z"
  }
]
```

---

### 3. Obtener Regla por ID

**GET** `/api/v1/alert_rules/{rule_id}`

Obtiene una regla activa de la organizacion autenticada.

#### Response `200 OK`

Devuelve un objeto `AlertRule`.

#### Errores comunes

- `404 Not Found`: la regla no existe, no pertenece a la organizacion o esta inactiva

---

### 4. Actualizar Regla de Alerta

**PATCH** `/api/v1/alert_rules/{rule_id}`

Todos los campos son opcionales. Solo se actualizan los enviados.

#### Request Body

```json
{
  "name": "Regla ignicion off actualizada",
  "config": {
    "event": "Engine OFF",
    "threshold": {
      "max": 10,
      "min": 1
    }
  },
  "unit_ids": [
    "550e8400-e29b-41d4-a716-446655440011"
  ]
}
```

#### Consideraciones

- Si `config` se envia, se vuelve a normalizar antes de guardar
- Si `unit_ids` se envia, reemplaza la lista anterior de unidades asociadas
- Si el fingerprint final colisiona con otra regla, responde `409 Conflict`

#### Response `200 OK`

Devuelve el objeto `AlertRule` actualizado.

---

### 5. Desactivar Regla

**DELETE** `/api/v1/alert_rules/{rule_id}`

Desactiva la regla sin eliminar el registro fisico.

#### Response `200 OK`

```json
{
  "message": "Regla desactivada exitosamente",
  "rule_id": "550e8400-e29b-41d4-a716-446655440000",
  "is_active": false
}
```

---

### 6. Asignar Unidades a una Regla

**POST** `/api/v1/alert_rules/{rule_id}/units`

Agrega unidades a la regla. Las ya asociadas se ignoran silenciosamente.

#### Request Body

```json
{
  "unit_ids": [
    "550e8400-e29b-41d4-a716-446655440010",
    "550e8400-e29b-41d4-a716-446655440011"
  ]
}
```

#### Response `200 OK`

```json
{
  "rule_id": "550e8400-e29b-41d4-a716-446655440000",
  "unit_ids": [
    "550e8400-e29b-41d4-a716-446655440010",
    "550e8400-e29b-41d4-a716-446655440011"
  ]
}
```

---

### 7. Desasignar Unidades de una Regla

**DELETE** `/api/v1/alert_rules/{rule_id}/units`

Elimina las asociaciones indicadas para la regla.

#### Request Body

```json
{
  "unit_ids": [
    "550e8400-e29b-41d4-a716-446655440010"
  ]
}
```

#### Response `200 OK`

```json
{
  "rule_id": "550e8400-e29b-41d4-a716-446655440000",
  "unit_ids": [
    "550e8400-e29b-41d4-a716-446655440010"
  ]
}
```

> Nota: la respuesta devuelve los `unit_ids` procesados en la desasignacion, no el estado final completo de la regla.

---

### 8. Listar Alertas Generadas

**GET** `/api/v1/alerts`

Lista alertas de una unidad dentro de la organizacion autenticada.

#### Query Parameters

| Parametro | Tipo | Requerido | Descripcion |
| --- | --- | --- | --- |
| `unit_id` | UUID | No | Unidad a consultar |
| `type` | string | No | Filtra por tipo exacto |
| `date_from` | datetime ISO 8601 | No | Retorna alertas con `occurred_at >= date_from` |
| `date_to` | datetime ISO 8601 | No | Retorna alertas con `occurred_at <= date_to` |
| `limit` | integer | No | Default `100`, minimo `1`, maximo `500` |
| `offset` | integer | No | Default `0` |

Si no se envía `unit_id`, el endpoint devuelve las ultimas 20 alertas de la organizacion autenticada (sin filtrar por unidad).

#### Response `200 OK`

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440100",
    "organization_id": "550e8400-e29b-41d4-a716-446655440001",
    "rule_id": "550e8400-e29b-41d4-a716-446655440000",
    "unit_id": "550e8400-e29b-41d4-a716-446655440010",
    "source_type": "event",
    "source_id": "evt-12345",
    "type": "ignition_off",
    "payload": {
      "event": "Engine OFF",
      "speed": 0
    },
    "occurred_at": "2026-04-05T09:58:00Z",
    "created_at": "2026-04-05T09:58:01Z"
  }
]
```

#### Errores comunes

- `404 Not Found`: la unidad no existe, no pertenece a la organizacion o fue eliminada logicamente

---

## Errores Frecuentes

| Codigo | Caso |
| --- | --- |
| `400 Bad Request` | Alguno de los `unit_ids` no pertenece a la organizacion o no esta activo |
| `401 Unauthorized` | Token ausente o invalido |
| `404 Not Found` | Regla o unidad no encontrada |
| `409 Conflict` | Regla duplicada por fingerprint |

---

## Ejemplos de Uso con cURL

### cURL: Crear regla con unidades

```bash
curl -X POST "http://localhost:8000/api/v1/alert_rules" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Regla ignicion off",
    "type": "ignition_off",
    "config": {
      "event": "Engine OFF"
    },
    "unit_ids": [
      "550e8400-e29b-41d4-a716-446655440010",
      "550e8400-e29b-41d4-a716-446655440011"
    ]
  }'
```

### cURL: Listar reglas activas de la organizacion

```bash
curl -X GET "http://localhost:8000/api/v1/alert_rules" \
  -H "Authorization: Bearer <token>"
```

### cURL: Filtrar reglas por unidad y tipo

```bash
curl -X GET "http://localhost:8000/api/v1/alert_rules?type=ignition_off&unit_id=550e8400-e29b-41d4-a716-446655440010" \
  -H "Authorization: Bearer <token>"
```

### cURL: Obtener una regla puntual

```bash
curl -X GET "http://localhost:8000/api/v1/alert_rules/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer <token>"
```

### cURL: Actualizar una regla

```bash
curl -X PATCH "http://localhost:8000/api/v1/alert_rules/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Regla ignicion off actualizada",
    "unit_ids": [
      "550e8400-e29b-41d4-a716-446655440011"
    ]
  }'
```

### cURL: Desactivar una regla

```bash
curl -X DELETE "http://localhost:8000/api/v1/alert_rules/550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer <token>"
```

### cURL: Asignar unidades a una regla

```bash
curl -X POST "http://localhost:8000/api/v1/alert_rules/550e8400-e29b-41d4-a716-446655440000/units" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "unit_ids": [
      "550e8400-e29b-41d4-a716-446655440010",
      "550e8400-e29b-41d4-a716-446655440011"
    ]
  }'
```

### cURL: Desasignar unidades de una regla

```bash
curl -X DELETE "http://localhost:8000/api/v1/alert_rules/550e8400-e29b-41d4-a716-446655440000/units" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "unit_ids": [
      "550e8400-e29b-41d4-a716-446655440010"
    ]
  }'
```

### cURL: Listar alertas por unidad y rango de fecha

```bash
curl -X GET "http://localhost:8000/api/v1/alerts?unit_id=550e8400-e29b-41d4-a716-446655440010&date_from=2026-04-01T00:00:00&date_to=2026-04-05T23:59:59&limit=100&offset=0" \
  -H "Authorization: Bearer <token>"
```

### cURL: Filtrar alertas por tipo

```bash
curl -X GET "http://localhost:8000/api/v1/alerts?unit_id=550e8400-e29b-41d4-a716-446655440010&type=ignition_off" \
  -H "Authorization: Bearer <token>"
```

---

**Ultima actualizacion**: 5 de abril de 2026  
**Referencia**: [API principal](../../API_DOCUMENTATION.md) | [Documentacion de unidades](./units.md)

# API de Alertas

## Descripción

Endpoints para gestionar reglas de alerta por organización y consultar alertas generadas por las unidades visibles para el usuario autenticado.

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
| Visibilidad por unidad | Usuarios `is_master` ven alertas de todas las unidades activas de la organizacion; usuarios normales solo de sus unidades asignadas en `user_units` |
| Delete fisico | `DELETE /alert_rules/{rule_id}` elimina la regla de la BD, borra sus asignaciones y deja `alerts.rule_id` en `null` |
| Deduplicacion | Crear o actualizar una regla puede responder `409` si el fingerprint colisiona con otra regla activa o existente |
| Unidades validas | Los `unit_ids` deben pertenecer a la organizacion del usuario y no estar eliminados |
| Filtro por unidad en alertas | Si se envia `unit_id`, el endpoint valida que la unidad pertenezca a la organizacion y que el usuario tenga acceso a ella |
| Normalizacion de config | `config` se normaliza antes de persistir: elimina claves con `null` y ordena llaves de forma deterministica |

### Fingerprint de reglas

El backend genera un fingerprint SHA-256 a partir de:

```text
organization_id|type|canonical_json(config)
```

Si el fingerprint ya existe, la API responde `409 Conflict`. El fingerprint **no incluye** `name` ni `unit_ids`; solo `organization_id`, `type` y `config` normalizado. Por eso dos reglas con distinto nombre o distintas unidades pero mismo `type` y `config` colisionan.

**Ejemplo:** se intenta crear una segunda regla `ignition_on` con el mismo `config` que una ya existente:

```http
POST /api/v1/alert_rules

{
  "unit_ids": ["18961401-9405-4124-8d2a-e2c445d11e1a"],
  "config": {"event": "Engine ON"},
  "name": "Prueba",
  "type": "ignition_on"
}
```

Respuesta:

```json
{
  "id": "550e8400-e29b-41d4-a716-446655449999",
  "message": "Ya existe una regla con el mismo tipo y configuracion para esta organizacion",
  "detail": "El fingerprint se genera con organization_id, type y config normalizado. Cambia el tipo o la configuracion de la regla para crear una nueva.",
  "existing_rule": {
    "id": "550e8400-e29b-41d4-a716-446655449999",
    "name": "Regla ignition on existente",
    "type": "ignition_on",
    "is_active": true
  }
}
```

> **Nota:** el campo `id` de raiz y `existing_rule.id` son el mismo; se expone en raiz por compatibilidad con clientes previos.

### Por que `unit_ids` no evita la colision

Las unidades se guardan en la tabla `alert_rule_units`, separadas de `alert_rules`. El fingerprint solo cubre la semantica de la regla (`type` + `config`), no a que unidades aplica. Si necesitas la misma logica en unidades distintas, crea la regla una sola vez y luego asigna las unidades con `POST /api/v1/alert_rules/{rule_id}/units`.

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

Se produce cuando ya existe una regla activa (o inactiva no eliminada) con el mismo `organization_id`, `type` y `config` normalizado.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655449999",
  "message": "Ya existe una regla con el mismo tipo y configuracion para esta organizacion",
  "detail": "El fingerprint se genera con organization_id, type y config normalizado. Cambia el tipo o la configuracion de la regla para crear una nueva.",
  "existing_rule": {
    "id": "550e8400-e29b-41d4-a716-446655449999",
    "name": "Regla ignition on existente",
    "type": "ignition_on",
    "is_active": true
  }
}
```

**Campos:**

| Campo | Descripcion |
| --- | --- |
| `id` | ID de la regla que ya existe (atajo para acceso rapido) |
| `message` | Descripcion del conflicto |
| `detail` | Explicacion de como se construye el fingerprint y como resolverlo |
| `existing_rule.id` | UUID de la regla existente |
| `existing_rule.name` | Nombre actual de esa regla |
| `existing_rule.type` | Tipo de la regla (`ignition_on`, `ignition_off`, etc.) |
| `existing_rule.is_active` | Si `true`, la regla esta activa; si `false`, fue eliminada logicamente pero el fingerprint sigue ocupado (ver endpoint DELETE) |

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

#### Response `409 Conflict`

Mismo formato que el `POST`. Se produce si al actualizar `type` o `config` el nuevo fingerprint ya lo tiene otra regla distinta.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655449888",
  "message": "Ya existe una regla con el mismo tipo y configuracion para esta organizacion",
  "detail": "El fingerprint se genera con organization_id, type y config normalizado. Cambia el tipo o la configuracion de la regla para crear una nueva.",
  "existing_rule": {
    "id": "550e8400-e29b-41d4-a716-446655449888",
    "name": "Regla ignition on existente",
    "type": "ignition_on",
    "is_active": true
  }
}
```

---

### 5. Eliminar Regla

**DELETE** `/api/v1/alert_rules/{rule_id}`

Elimina la regla de forma fisica.

#### Efectos secundarios

- Elimina las relaciones en `alert_rule_units`
- Las alertas historicas que referenciaban la regla conservan su registro, pero `rule_id` pasa a `null`

#### Response `200 OK`

```json
{
  "message": "Regla eliminada exitosamente",
  "rule_id": "550e8400-e29b-41d4-a716-446655440000",
  "deleted": true
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

Lista alertas visibles para el usuario autenticado dentro de su organizacion.

#### Query Parameters

| Parametro | Tipo | Requerido | Descripcion |
| --- | --- | --- | --- |
| `unit_id` | UUID | No | Unidad a consultar; debe estar dentro del alcance del usuario autenticado |
| `type` | string | No | Filtra por tipo exacto |
| `date_from` | datetime ISO 8601 | No | Retorna alertas con `occurred_at >= date_from` |
| `date_to` | datetime ISO 8601 | No | Retorna alertas con `occurred_at <= date_to` |
| `limit` | integer | No | Default `100`, minimo `1`, maximo `500`. Si no se envia `unit_id`, el backend fuerza `limit=20` |
| `offset` | integer | No | Default `0`. Si no se envia `unit_id`, el backend fuerza `offset=0` |

Si no se envía `unit_id`, el endpoint devuelve las ultimas 20 alertas visibles para el usuario autenticado. Para usuarios `is_master`, esto incluye todas las unidades activas de la organizacion. Para usuarios normales, solo incluye sus unidades asignadas en `user_units`.

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

- `403 Forbidden`: la unidad pertenece a la organizacion, pero el usuario no tiene permiso para consultarla
- `404 Not Found`: la unidad no existe, no pertenece a la organizacion o fue eliminada logicamente

#### Response `403 Forbidden`

```json
{
  "detail": "No tienes permiso para acceder a esta unidad"
}
```

---

## Errores Frecuentes

| Codigo | Caso |
| --- | --- |
| `400 Bad Request` | Alguno de los `unit_ids` no pertenece a la organizacion o no esta activo |
| `401 Unauthorized` | Token ausente o invalido |
| `403 Forbidden` | El usuario no tiene acceso a la unidad solicitada |
| `404 Not Found` | Regla o unidad no encontrada |
| `409 Conflict` | Regla duplicada por fingerprint |

---

## Eventos Kafka de Reglas

Los endpoints que escriben en `alert_rules` o `alert_rule_units` publican un evento en Kafka **despues** de confirmar transaccion en BD.

La BD es la fuente de verdad. Si falla la publicacion en Kafka:

- La respuesta HTTP del endpoint exitoso se mantiene.
- No se hace rollback de BD.
- Se registra error en logs con contexto de operacion.
- No hay reintentos automaticos.

### Variables de Entorno

```text
KAFKA_BROKERS=localhost:9092
KAFKA_RULES_UPDATES_TOPIC=alert-rules-updates
KAFKA_RULES_UPDATES_GROUP_ID=alert-rules-updates-group
KAFKA_SASL_USERNAME=events-alert-consumer
KAFKA_SASL_PASSWORD=eventsalertconsumerpassword
KAFKA_SASL_MECHANISM=SCRAM-SHA-256
KAFKA_SECURITY_PROTOCOL=SASL_PLAINTEXT
```

### Operaciones que Publican

- `POST /api/v1/alert_rules` -> `UPSERT`
- `PATCH /api/v1/alert_rules/{rule_id}` -> `UPSERT`
- `DELETE /api/v1/alert_rules/{rule_id}` -> `DELETE`
- `POST /api/v1/alert_rules/{rule_id}/units` -> `UPSERT`
- `DELETE /api/v1/alert_rules/{rule_id}/units` -> `UPSERT`

### Payload UPSERT

```json
{
  "operation": "UPSERT",
  "rule": {
    "id": "3b6afa2b-0f8d-4ef2-bdbf-bb20c8af9ae6",
    "organization_id": "c24ba579-6a27-42d9-a398-0486fbe54f8c",
    "name": "Encendido",
    "type": "ignition_on",
    "config": {
      "event": "Engine ON"
    },
    "unit_ids": [
      "18961401-9405-4124-8d2a-e2c445d11e1a"
    ],
    "is_active": true,
    "updated_at": "2026-04-05T23:25:03.582955Z"
  },
  "context": {
    "units": [
      {
        "id": "18961401-9405-4124-8d2a-e2c445d11e1a",
        "name": "Camioneta Juan"
      }
    ]
  }
}
```

#### Descripción de campos UPSERT

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `operation` | `string` | Siempre `UPSERT` para operaciones de creación o actualización |
| `rule.id` | `UUID` | ID único de la regla |
| `rule.organization_id` | `UUID` | ID de la organización propietaria de la regla |
| `rule.name` | `string` | Nombre descriptivo de la regla |
| `rule.type` | `string` | Tipo de regla (ej: `ignition_on`, `ignition_off`, `geofence`, etc.) |
| `rule.config` | `object` | Configuración específica de la regla según su tipo |
| `rule.unit_ids` | `UUID[]` | Lista de IDs de unidades asociadas a la regla |
| `rule.is_active` | `boolean` | Indica si la regla está activa |
| `rule.updated_at` | `ISO 8601` | Timestamp de la última actualización en formato UTC ISO con sufijo Z |
| `context.units` | `object[]` | Arreglo con información enriquecida de las unidades |
| `context.units[].id` | `UUID` | ID de la unidad |
| `context.units[].name` | `string` | Nombre descriptivo de la unidad |


### Payload DELETE

```json
{
  "operation": "DELETE",
  "rule_id": "3b6afa2b-0f8d-4ef2-bdbf-bb20c8af9ae6",
  "updated_at": "2026-04-05T23:30:00Z"
}
```

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

### cURL: Intentar consultar una unidad sin permiso (403)

```bash
curl -X GET "http://localhost:8000/api/v1/alerts?unit_id=550e8400-e29b-41d4-a716-446655449999" \
  -H "Authorization: Bearer <token>"
```

---

**Ultima actualizacion**: 14 de abril de 2026  
**Referencia**: [API principal](../../API_DOCUMENTATION.md) | [Documentacion de unidades](./units.md)

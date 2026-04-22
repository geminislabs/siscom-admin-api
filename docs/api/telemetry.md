# API de Telemetría Agregada

## Descripción

Endpoints para consultar métricas agregadas de dispositivos GPS en tiempo real e histórico.

La información proviene de `telemetry_hourly_stats`, una tabla pre-procesada que recibe datos de Kafka y almacena estadísticas por hora. El API transforma esos datos crudos en métricas semánticas listas para dashboards y reportes.

```
Dispositivo GPS → Kafka → telemetry_hourly_stats → API (agregación) → Cliente
```

**Principios de diseño:**
- Solo se exponen métricas calculadas (`avg_speed`, `max_speed`, etc.), nunca sumatorias ni contadores internos (`sum_*`, `count_*`).
- El rango de consulta es **semiabierto** `[from, to)` — el instante `to` es exclusivo, lo que permite consultas contiguas sin doble conteo.
- Solo se retornan buckets que tienen datos; no se rellenan períodos vacíos.
- El usuario autenticado solo puede consultar dispositivos accesibles vía sus unidades asignadas.
- Los campos de métricas no solicitados se omiten completamente de la respuesta (no aparece `null`).

## Índice de casos de uso

| # | Caso de uso | Endpoint | Granularidad |
|---|------------|----------|--------------|
| 1 | [Velocidad de un vehículo hoy (por hora)](#caso-1-velocidad-de-un-vehículo-hoy-por-hora) | GET | hour |
| 2 | [Reporte semanal de velocidad (por día)](#caso-2-reporte-semanal-de-velocidad-por-día) | GET | day |
| 3 | [Monitoreo de batería en tiempo real](#caso-3-monitoreo-de-batería-en-tiempo-real) | GET | hour |
| 4 | [Reporte mensual de batería](#caso-4-reporte-mensual-de-batería) | GET | day |
| 5 | [Alertas del día para un vehículo](#caso-5-alertas-del-día-para-un-vehículo) | GET | hour |
| 6 | [Dashboard completo de un vehículo (todas las métricas)](#caso-6-dashboard-completo-de-un-vehículo) | GET | hour |
| 7 | [Comparativa de flota — velocidad](#caso-7-comparativa-de-flota--velocidad) | POST | hour |
| 8 | [Reporte mensual de flota (por día)](#caso-8-reporte-mensual-de-flota-por-día) | POST | day |
| 9 | [Calidad de comunicación de múltiples dispositivos](#caso-9-calidad-de-comunicación-de-múltiples-dispositivos) | POST | day |

---

---

## Referencia de endpoints

### GET `/api/v1/devices/{device_id}/telemetry`

Retorna la serie temporal de métricas para un único dispositivo.

#### Headers

```
Authorization: Bearer <access_token>
```

#### Path parameters

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `device_id` | string | ID del dispositivo GPS (IMEI u otro identificador) |

#### Query parameters

| Parámetro | Tipo | Requerido | Default | Descripción |
|-----------|------|-----------|---------|-------------|
| `from` | datetime | Sí | — | Inicio del rango (inclusivo). ISO 8601 con zona horaria, ej. `2026-04-21T00:00:00Z` |
| `to` | datetime | Sí | — | Fin del rango (exclusivo). ISO 8601 con zona horaria |
| `granularity` | string | No | `hour` | Agrupación temporal: `hour` o `day` |
| `metrics` | string[] | Sí | — | Métricas a incluir. Repetir el parámetro: `?metrics=speed&metrics=alerts` |

#### Métricas disponibles

| Valor | Campos en respuesta | Unidad | Descripción |
|-------|---------------------|--------|-------------|
| `speed` | `avg_speed`, `max_speed` | km/h | Velocidad promedio y máxima en el período |
| `main_battery` | `avg_voltage`, `min_voltage` | V | Tensión de la batería principal |
| `backup_battery` | `avg_voltage`, `min_voltage` | V | Tensión de la batería de respaldo |
| `alerts` | `count` | — | Total de alertas generadas en el período |
| `comm_quality` | `fixable_count`, `with_fix_count` | — | Mensajes con error recuperable y mensajes con corrección GPS aplicada |
| `samples` | `total` | — | Total de mensajes procesados en el período |

#### Límites de rango

| Granularidad | Máximo | Uso típico |
|--------------|--------|------------|
| `hour` | 7 días | Dashboards en tiempo real, análisis de jornada |
| `day` | 180 días | Reportes mensuales, tendencias históricas |

#### Errores

| Código | Causa | Ejemplo de `detail` |
|--------|-------|---------------------|
| `400` | Rango inválido, métricas inválidas o vacías, límite superado | `"Con granularity=hour el rango máximo es 7 días"` |
| `400` | `from` >= `to` | `"'from' debe ser anterior a 'to'"` |
| `400` | Sin métricas | `"Se debe especificar al menos una métrica"` |
| `400` | Métrica desconocida | `"Métricas no válidas: ['temperatura']"` |
| `401` | Sin token | `"Not authenticated"` |
| `404` | Dispositivo sin acceso o inexistente | `"Dispositivo no encontrado"` |
| `422` | Parámetro con formato inválido | `[{"loc": ["query", "granularity"], "msg": "..."}]` |

---

### POST `/api/v1/telemetry/query`

Consulta telemetría de múltiples dispositivos en una sola llamada. Útil para dashboards de flota.

#### Headers

```
Authorization: Bearer <access_token>
Content-Type: application/json
```

#### Request body

| Campo | Tipo | Requerido | Default | Descripción |
|-------|------|-----------|---------|-------------|
| `device_ids` | string[] | Sí | — | IDs de dispositivos (máximo 50, se deduplicán automáticamente) |
| `from` | datetime | Sí | — | Inicio del rango (inclusivo, timezone-aware) |
| `to` | datetime | Sí | — | Fin del rango (exclusivo, timezone-aware) |
| `granularity` | string | No | `hour` | `hour` o `day` |
| `metrics` | string[] | Sí | — | Métricas a incluir (mismos valores que el GET) |

#### Errores

| Código | Causa | Ejemplo de `detail` |
|--------|-------|---------------------|
| `404` | Algún `device_id` no es accesible | `"Uno o más dispositivos no encontrados"` |
| `422` | Más de 50 dispositivos | `"Se permiten máximo 50 dispositivos por consulta"` |
| `422` | `from` >= `to` | `"'from' debe ser anterior a 'to'"` |
| `422` | Rango excede el límite | `"Con granularity=hour el rango máximo es 7 días"` |
| `422` | `device_ids` vacío | error de validación Pydantic |

> El 404 es genérico aunque el dispositivo exista en otro contexto. Esto evita filtrar información de existencia a usuarios sin acceso.

---

## Comportamiento de granularidad

### `granularity=hour`

Retorna los buckets tal como están almacenados en `telemetry_hourly_stats`. Cada punto representa exactamente una hora. Los promedios se calculan como `SUM(suma) / COUNT(registros)`.

- Rango máximo: **7 días**
- El campo `bucket` es la hora en punto UTC: `2026-04-21T14:00:00Z`
- Si no hay actividad en una hora, ese bucket no aparece

### `granularity=day`

Re-agrega los buckets horarios por día calendario en UTC (`date_trunc('day', bucket)`). Permite ver tendencias sin saturar la vista con 24 puntos por día.

- Rango máximo: **180 días**
- El campo `bucket` es la medianoche UTC del día: `2026-04-21T00:00:00Z`
- Los cálculos son estadísticamente correctos:

| Métrica | Fórmula día |
|---------|-------------|
| `avg_speed`, `avg_voltage` | `SUM(suma_horaria) / SUM(conteo_horario)` — **no** promedio de promedios |
| `max_speed`, `min_voltage` | `MAX/MIN` sobre todos los registros del día |
| `alerts.count`, `samples.total` | `SUM` de todos los buckets del día |
| `comm_quality` | `SUM` de `fixable_count` y `with_fix_count` del día |

---

## Notas de acceso y seguridad

- **Usuario master** (`is_master=true`): puede consultar cualquier dispositivo de su organización.
- **Usuario normal**: solo puede consultar dispositivos vinculados a unidades asignadas en `user_units → unit_devices`.
- El control de acceso se evalúa antes de ejecutar cualquier query de telemetría.
- Se responde `404` (no `403`) cuando el dispositivo no es accesible, para no exponer si el device existe en otra organización.

---

## Notas de rendimiento

- Las queries usan el índice primario `(device_id, bucket)` de `telemetry_hourly_stats` — el filtro `device_id` siempre aparece primero.
- La consulta batch usa `device_id = ANY(:array)` para una sola query en lugar de N consultas independientes.
- Los campos no solicitados se omiten de la respuesta (`response_model_exclude_none=True`), reduciendo el tamaño del payload.
- Los timestamps en la respuesta están siempre en UTC. Para mostrarlos en hora local, convertir `bucket` en el cliente.

---

## Casos de uso

### Caso 1: Velocidad de un vehículo hoy (por hora)

Útil para un dashboard que muestra la actividad del día en curso con resolución horaria.

```bash
curl -G "https://api.ejemplo.com/api/v1/devices/864537040123456/telemetry" \
  -H "Authorization: Bearer <token>" \
  --data-urlencode "from=2026-04-21T00:00:00Z" \
  --data-urlencode "to=2026-04-22T00:00:00Z" \
  -d "granularity=hour" \
  -d "metrics=speed"
```

**Respuesta 200 OK:**

```json
{
  "device_id": "864537040123456",
  "granularity": "hour",
  "from": "2026-04-21T00:00:00Z",
  "to": "2026-04-22T00:00:00Z",
  "metrics": ["speed"],
  "series": [
    {
      "bucket": "2026-04-21T08:00:00Z",
      "speed": { "avg_speed": 0.0, "max_speed": 0.0 }
    },
    {
      "bucket": "2026-04-21T09:00:00Z",
      "speed": { "avg_speed": 42.3, "max_speed": 87.5 }
    },
    {
      "bucket": "2026-04-21T10:00:00Z",
      "speed": { "avg_speed": 61.1, "max_speed": 112.0 }
    },
    {
      "bucket": "2026-04-21T11:00:00Z",
      "speed": { "avg_speed": 38.7, "max_speed": 72.0 }
    },
    {
      "bucket": "2026-04-21T14:00:00Z",
      "speed": { "avg_speed": 55.4, "max_speed": 95.0 }
    }
  ]
}
```

> Las horas 00:00–07:00 y 12:00–13:00 no aparecen porque el vehículo no transmitió datos en esos períodos.

---

### Caso 2: Reporte semanal de velocidad (por día)

Ideal para un reporte de la última semana que muestre la actividad diaria sin saturar con 168 puntos horarios.

```bash
curl -G "https://api.ejemplo.com/api/v1/devices/864537040123456/telemetry" \
  -H "Authorization: Bearer <token>" \
  --data-urlencode "from=2026-04-14T00:00:00Z" \
  --data-urlencode "to=2026-04-21T00:00:00Z" \
  -d "granularity=day" \
  -d "metrics=speed"
```

**Respuesta 200 OK:**

```json
{
  "device_id": "864537040123456",
  "granularity": "day",
  "from": "2026-04-14T00:00:00Z",
  "to": "2026-04-21T00:00:00Z",
  "metrics": ["speed"],
  "series": [
    {
      "bucket": "2026-04-14T00:00:00Z",
      "speed": { "avg_speed": 48.2, "max_speed": 112.0 }
    },
    {
      "bucket": "2026-04-15T00:00:00Z",
      "speed": { "avg_speed": 53.1, "max_speed": 98.5 }
    },
    {
      "bucket": "2026-04-17T00:00:00Z",
      "speed": { "avg_speed": 44.0, "max_speed": 88.3 }
    },
    {
      "bucket": "2026-04-18T00:00:00Z",
      "speed": { "avg_speed": 60.2, "max_speed": 120.5 }
    },
    {
      "bucket": "2026-04-20T00:00:00Z",
      "speed": { "avg_speed": 39.8, "max_speed": 75.0 }
    }
  ]
}
```

> Los días 16 y 19 no aparecen porque el vehículo no reportó actividad (fines de semana sin operación). El `avg_speed` del día es calculado correctamente desde los acumulados horarios, no como promedio de promedios.

---

### Caso 3: Monitoreo de batería en tiempo real

Muestra el estado de la batería principal y de respaldo en las últimas 6 horas. Útil para detectar caídas de voltaje que indican problemas eléctricos.

```bash
curl -G "https://api.ejemplo.com/api/v1/devices/864537040123456/telemetry" \
  -H "Authorization: Bearer <token>" \
  --data-urlencode "from=2026-04-21T08:00:00Z" \
  --data-urlencode "to=2026-04-21T14:00:00Z" \
  -d "granularity=hour" \
  -d "metrics=main_battery" \
  -d "metrics=backup_battery"
```

**Respuesta 200 OK:**

```json
{
  "device_id": "864537040123456",
  "granularity": "hour",
  "from": "2026-04-21T08:00:00Z",
  "to": "2026-04-21T14:00:00Z",
  "metrics": ["main_battery", "backup_battery"],
  "series": [
    {
      "bucket": "2026-04-21T08:00:00Z",
      "main_battery": { "avg_voltage": 12.8, "min_voltage": 12.6 },
      "backup_battery": { "avg_voltage": 3.9, "min_voltage": 3.8 }
    },
    {
      "bucket": "2026-04-21T09:00:00Z",
      "main_battery": { "avg_voltage": 12.5, "min_voltage": 11.9 },
      "backup_battery": { "avg_voltage": 3.9, "min_voltage": 3.9 }
    },
    {
      "bucket": "2026-04-21T10:00:00Z",
      "main_battery": { "avg_voltage": 11.8, "min_voltage": 10.2 },
      "backup_battery": { "avg_voltage": 3.7, "min_voltage": 3.5 }
    },
    {
      "bucket": "2026-04-21T11:00:00Z",
      "main_battery": { "avg_voltage": 12.7, "min_voltage": 12.5 },
      "backup_battery": { "avg_voltage": 3.9, "min_voltage": 3.9 }
    }
  ]
}
```

> La caída a `min_voltage: 10.2` en la hora 10:00 puede indicar un problema eléctrico momentáneo. El `min_voltage` captura el peor caso del período, útil para alertas de umbral.

---

### Caso 4: Reporte mensual de batería

Análisis de la tendencia de voltaje durante los últimos 30 días para programar mantenimiento preventivo.

```bash
curl -G "https://api.ejemplo.com/api/v1/devices/864537040123456/telemetry" \
  -H "Authorization: Bearer <token>" \
  --data-urlencode "from=2026-03-22T00:00:00Z" \
  --data-urlencode "to=2026-04-22T00:00:00Z" \
  -d "granularity=day" \
  -d "metrics=main_battery"
```

**Respuesta 200 OK (fragmento):**

```json
{
  "device_id": "864537040123456",
  "granularity": "day",
  "from": "2026-03-22T00:00:00Z",
  "to": "2026-04-22T00:00:00Z",
  "metrics": ["main_battery"],
  "series": [
    {
      "bucket": "2026-03-22T00:00:00Z",
      "main_battery": { "avg_voltage": 12.8, "min_voltage": 12.4 }
    },
    {
      "bucket": "2026-03-29T00:00:00Z",
      "main_battery": { "avg_voltage": 12.6, "min_voltage": 12.1 }
    },
    {
      "bucket": "2026-04-05T00:00:00Z",
      "main_battery": { "avg_voltage": 12.3, "min_voltage": 11.5 }
    },
    {
      "bucket": "2026-04-12T00:00:00Z",
      "main_battery": { "avg_voltage": 11.9, "min_voltage": 10.8 }
    },
    {
      "bucket": "2026-04-19T00:00:00Z",
      "main_battery": { "avg_voltage": 11.5, "min_voltage": 10.2 }
    }
  ]
}
```

> La tendencia descendente en `avg_voltage` (12.8 → 11.5 en 4 semanas) y el `min_voltage` cayendo bajo 11V indican degradación de batería.

---

### Caso 5: Alertas del día para un vehículo

Identifica en qué horas se generaron más alertas durante la jornada de hoy.

```bash
curl -G "https://api.ejemplo.com/api/v1/devices/864537040123456/telemetry" \
  -H "Authorization: Bearer <token>" \
  --data-urlencode "from=2026-04-21T06:00:00Z" \
  --data-urlencode "to=2026-04-21T22:00:00Z" \
  -d "granularity=hour" \
  -d "metrics=alerts" \
  -d "metrics=samples"
```

**Respuesta 200 OK:**

```json
{
  "device_id": "864537040123456",
  "granularity": "hour",
  "from": "2026-04-21T06:00:00Z",
  "to": "2026-04-21T22:00:00Z",
  "metrics": ["alerts", "samples"],
  "series": [
    {
      "bucket": "2026-04-21T08:00:00Z",
      "alerts": { "count": 0 },
      "samples": { "total": 120 }
    },
    {
      "bucket": "2026-04-21T09:00:00Z",
      "alerts": { "count": 3 },
      "samples": { "total": 118 }
    },
    {
      "bucket": "2026-04-21T13:00:00Z",
      "alerts": { "count": 1 },
      "samples": { "total": 115 }
    },
    {
      "bucket": "2026-04-21T17:00:00Z",
      "alerts": { "count": 7 },
      "samples": { "total": 122 }
    },
    {
      "bucket": "2026-04-21T18:00:00Z",
      "alerts": { "count": 2 },
      "samples": { "total": 119 }
    }
  ]
}
```

> `samples.total` junto con `alerts.count` permite calcular la tasa de alertas por mensaje (`7/122 = 5.7%` en la hora 17:00). Las horas sin datos no aparecen.

---

### Caso 6: Dashboard completo de un vehículo

Solicita todas las métricas para mostrar un panel unificado de salud del dispositivo en las últimas 4 horas.

```bash
curl -G "https://api.ejemplo.com/api/v1/devices/864537040123456/telemetry" \
  -H "Authorization: Bearer <token>" \
  --data-urlencode "from=2026-04-21T10:00:00Z" \
  --data-urlencode "to=2026-04-21T14:00:00Z" \
  -d "granularity=hour" \
  -d "metrics=speed" \
  -d "metrics=main_battery" \
  -d "metrics=backup_battery" \
  -d "metrics=alerts" \
  -d "metrics=comm_quality" \
  -d "metrics=samples"
```

**Respuesta 200 OK:**

```json
{
  "device_id": "864537040123456",
  "granularity": "hour",
  "from": "2026-04-21T10:00:00Z",
  "to": "2026-04-21T14:00:00Z",
  "metrics": ["speed", "main_battery", "backup_battery", "alerts", "comm_quality", "samples"],
  "series": [
    {
      "bucket": "2026-04-21T10:00:00Z",
      "speed": { "avg_speed": 58.3, "max_speed": 95.0 },
      "main_battery": { "avg_voltage": 12.7, "min_voltage": 12.4 },
      "backup_battery": { "avg_voltage": 3.9, "min_voltage": 3.8 },
      "alerts": { "count": 1 },
      "comm_quality": { "fixable_count": 2, "with_fix_count": 118 },
      "samples": { "total": 120 }
    },
    {
      "bucket": "2026-04-21T11:00:00Z",
      "speed": { "avg_speed": 43.1, "max_speed": 78.0 },
      "main_battery": { "avg_voltage": 12.6, "min_voltage": 12.3 },
      "backup_battery": { "avg_voltage": 3.9, "min_voltage": 3.9 },
      "alerts": { "count": 0 },
      "comm_quality": { "fixable_count": 0, "with_fix_count": 115 },
      "samples": { "total": 115 }
    },
    {
      "bucket": "2026-04-21T13:00:00Z",
      "speed": { "avg_speed": 0.0, "max_speed": 0.0 },
      "main_battery": { "avg_voltage": 12.5, "min_voltage": 12.5 },
      "backup_battery": { "avg_voltage": 3.9, "min_voltage": 3.9 },
      "alerts": { "count": 0 },
      "comm_quality": { "fixable_count": 1, "with_fix_count": 59 },
      "samples": { "total": 60 }
    }
  ]
}
```

> La hora 12:00 no aparece porque el dispositivo no transmitió (posible parada de motor). La hora 13:00 muestra `avg_speed: 0.0` porque el vehículo estaba detenido pero el tracker seguía reportando.

---

### Caso 7: Comparativa de flota — velocidad

Permite comparar el comportamiento de velocidad de varios vehículos durante la misma ventana de tiempo. Ideal para rankear conductores o identificar rutas problemáticas.

```bash
curl -X POST "https://api.ejemplo.com/api/v1/telemetry/query" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_ids": [
      "864537040111111",
      "864537040222222",
      "864537040333333"
    ],
    "from": "2026-04-21T08:00:00Z",
    "to": "2026-04-21T18:00:00Z",
    "granularity": "hour",
    "metrics": ["speed", "alerts"]
  }'
```

**Respuesta 200 OK:**

```json
{
  "granularity": "hour",
  "from": "2026-04-21T08:00:00Z",
  "to": "2026-04-21T18:00:00Z",
  "metrics": ["speed", "alerts"],
  "devices": [
    {
      "device_id": "864537040111111",
      "series": [
        {
          "bucket": "2026-04-21T09:00:00Z",
          "speed": { "avg_speed": 65.2, "max_speed": 130.0 },
          "alerts": { "count": 4 }
        },
        {
          "bucket": "2026-04-21T10:00:00Z",
          "speed": { "avg_speed": 71.0, "max_speed": 140.5 },
          "alerts": { "count": 6 }
        }
      ]
    },
    {
      "device_id": "864537040222222",
      "series": [
        {
          "bucket": "2026-04-21T09:00:00Z",
          "speed": { "avg_speed": 48.1, "max_speed": 85.0 },
          "alerts": { "count": 0 }
        },
        {
          "bucket": "2026-04-21T10:00:00Z",
          "speed": { "avg_speed": 52.4, "max_speed": 90.0 },
          "alerts": { "count": 1 }
        },
        {
          "bucket": "2026-04-21T11:00:00Z",
          "speed": { "avg_speed": 44.0, "max_speed": 78.0 },
          "alerts": { "count": 0 }
        }
      ]
    },
    {
      "device_id": "864537040333333",
      "series": []
    }
  ]
}
```

> El dispositivo `864537040333333` no tiene actividad en el período — su `series` es lista vacía. El dispositivo `864537040111111` muestra velocidades máximas altas y muchas alertas, lo que puede indicar conducción agresiva.

---

### Caso 8: Reporte mensual de flota (por día)

Vista de resumen diario para toda la flota durante el mes anterior. Útil para reportes ejecutivos de operaciones.

```bash
curl -X POST "https://api.ejemplo.com/api/v1/telemetry/query" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_ids": [
      "864537040111111",
      "864537040222222",
      "864537040333333",
      "864537040444444"
    ],
    "from": "2026-03-01T00:00:00Z",
    "to": "2026-04-01T00:00:00Z",
    "granularity": "day",
    "metrics": ["speed", "alerts", "samples"]
  }'
```

**Respuesta 200 OK (fragmento):**

```json
{
  "granularity": "day",
  "from": "2026-03-01T00:00:00Z",
  "to": "2026-04-01T00:00:00Z",
  "metrics": ["speed", "alerts", "samples"],
  "devices": [
    {
      "device_id": "864537040111111",
      "series": [
        {
          "bucket": "2026-03-03T00:00:00Z",
          "speed": { "avg_speed": 62.1, "max_speed": 145.0 },
          "alerts": { "count": 12 },
          "samples": { "total": 1440 }
        },
        {
          "bucket": "2026-03-04T00:00:00Z",
          "speed": { "avg_speed": 58.3, "max_speed": 130.0 },
          "alerts": { "count": 8 },
          "samples": { "total": 1380 }
        }
      ]
    },
    {
      "device_id": "864537040222222",
      "series": [
        {
          "bucket": "2026-03-03T00:00:00Z",
          "speed": { "avg_speed": 47.2, "max_speed": 95.0 },
          "alerts": { "count": 2 },
          "samples": { "total": 1200 }
        }
      ]
    }
  ]
}
```

> Con `granularity=day` y un rango de 31 días se obtiene máximo 31 puntos por dispositivo, manejable para gráficas de tendencia. El máximo permitido es 180 días.

---

### Caso 9: Calidad de comunicación de múltiples dispositivos

Detecta dispositivos con problemas de GPS o conectividad comparando `with_fix_count` contra `samples.total`.

```bash
curl -X POST "https://api.ejemplo.com/api/v1/telemetry/query" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "device_ids": [
      "864537040111111",
      "864537040222222",
      "864537040333333"
    ],
    "from": "2026-04-14T00:00:00Z",
    "to": "2026-04-21T00:00:00Z",
    "granularity": "day",
    "metrics": ["comm_quality", "samples"]
  }'
```

**Respuesta 200 OK:**

```json
{
  "granularity": "day",
  "from": "2026-04-14T00:00:00Z",
  "to": "2026-04-21T00:00:00Z",
  "metrics": ["comm_quality", "samples"],
  "devices": [
    {
      "device_id": "864537040111111",
      "series": [
        {
          "bucket": "2026-04-14T00:00:00Z",
          "comm_quality": { "fixable_count": 5, "with_fix_count": 1435 },
          "samples": { "total": 1440 }
        },
        {
          "bucket": "2026-04-15T00:00:00Z",
          "comm_quality": { "fixable_count": 3, "with_fix_count": 1437 },
          "samples": { "total": 1440 }
        }
      ]
    },
    {
      "device_id": "864537040222222",
      "series": [
        {
          "bucket": "2026-04-14T00:00:00Z",
          "comm_quality": { "fixable_count": 280, "with_fix_count": 860 },
          "samples": { "total": 1440 }
        },
        {
          "bucket": "2026-04-15T00:00:00Z",
          "comm_quality": { "fixable_count": 310, "with_fix_count": 830 },
          "samples": { "total": 1440 }
        }
      ]
    }
  ]
}
```

> El dispositivo `864537040222222` tiene un ratio de `with_fix_count / total` de ~60% (frente al 99.7% del `111111`), lo que indica problemas persistentes de señal GPS. `fixable_count` alto puede indicar errores de checksum recuperables.

---

## Recomendaciones de mejora futura

| Mejora | Impacto | Complejidad |
|--------|---------|-------------|
| Caché corto por combinación `(device_ids, from, to, granularity, metrics)` | Reduce carga en picos de dashboard | Media |
| Vista materializada diaria en TimescaleDB (`telemetry_daily_stats`) | Elimina `date_trunc + GROUP BY` sobre ventanas largas | Media |
| Parámetro `tz` para bucket diario en hora local | Mejora UX para usuarios en zonas no-UTC | Baja |
| Paginación por cursor en series largas | Permite rangos más amplios con control de memoria | Media |
| Percentiles (`p95_speed`, `p99_speed`) | Análisis estadístico más robusto que el máximo puntual | Alta |

---

## Referencias

- [API de Eventos de Dispositivos](./device-events.md) — historial administrativo de dispositivos
- [API de Viajes](./trips.md) — viajes detectados con puntos GPS
- [API de Alertas](./alerts.md) — alertas generadas por reglas
- [Modelo Organizacional](../guides/organizational-model.md) — permisos y roles

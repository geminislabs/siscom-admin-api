# API de Ubicaciones de Movilidad

## Descripción

Endpoint para recibir ubicaciones de dispositivos de movilidad y publicarlas en Kafka.

El backend valida campos obligatorios del JSON, agrega `received_at` con la hora actual UTC y publica el mensaje enriquecido en el tópico configurado por `KAFKA_MOBILITY_TOPIC`.

---

## Endpoint

### `POST /api/v1/mobility/locations`

#### Request Body

Campos obligatorios:

- `device_id` (uuid)
- `recorded_at` (datetime)
- `lat` (number)
- `lon` (number)

Campos opcionales:

- `accuracy_m` (number)
- `speed_mps` (number)
- `heading` (number)
- `altitude_m` (number)
- `battery_level` (number entre 0 y 100)
- `h3_index` (string)
- `h3_resolution` (integer entre 0 y 15)

Ejemplo:

```json
{
  "device_id": "c7bb5f50-b8e6-4c7d-a0a2-c6fdb2b6f3f0",
  "recorded_at": "2026-05-31T02:15:20Z",
  "lat": 20.593212,
  "lon": -100.392188,
  "accuracy_m": 12.5,
  "speed_mps": 0.0,
  "heading": 180,
  "altitude_m": 1810,
  "battery_level": 82,
  "h3_index": "8a2a1072b59ffff",
  "h3_resolution": 10
}
```

#### Response 202 Accepted

Retorna el payload publicado, enriquecido con `received_at`:

```json
{
  "device_id": "c7bb5f50-b8e6-4c7d-a0a2-c6fdb2b6f3f0",
  "recorded_at": "2026-05-31T02:15:20Z",
  "received_at": "2026-05-31T02:15:21Z",
  "lat": 20.593212,
  "lon": -100.392188,
  "accuracy_m": 12.5,
  "speed_mps": 0.0,
  "heading": 180,
  "altitude_m": 1810,
  "battery_level": 82,
  "h3_index": "8a2a1072b59ffff",
  "h3_resolution": 10
}
```

---

### `POST /api/v1/mobility/locations/batch`

Publica un lote de ubicaciones para un mismo `device_id`.

#### Request Body

Campos obligatorios:

- `device_id` (uuid)
- `locations` (array con al menos un elemento)

Cada elemento en `locations`:

- Obligatorios: `recorded_at`, `lat`, `lon`
- Opcionales: `accuracy_m`, `speed_mps`, `heading`, `altitude_m`, `battery_level`, `h3_index`, `h3_resolution`

Ejemplo:

```json
{
  "device_id": "c7bb5f50-b8e6-4c7d-a0a2-c6fdb2b6f3f0",
  "locations": [
    {
      "recorded_at": "2026-05-31T10:00:00Z",
      "lat": 20.593,
      "lon": -100.392,
      "accuracy_m": 12,
      "h3_index": "8a2a1072b59ffff",
      "h3_resolution": 10
    },
    {
      "recorded_at": "2026-05-31T10:05:00Z",
      "lat": 20.594,
      "lon": -100.391,
      "accuracy_m": 10
    }
  ]
}
```

#### Response 202 Accepted

Retorna `device_id` y el arreglo de ubicaciones publicadas, enriquecidas con `received_at`:

```json
{
  "device_id": "c7bb5f50-b8e6-4c7d-a0a2-c6fdb2b6f3f0",
  "locations": [
    {
      "recorded_at": "2026-05-31T10:00:00Z",
      "received_at": "2026-05-31T10:00:01Z",
      "lat": 20.593,
      "lon": -100.392,
      "accuracy_m": 12,
      "h3_index": "8a2a1072b59ffff",
      "h3_resolution": 10
    },
    {
      "recorded_at": "2026-05-31T10:05:00Z",
      "received_at": "2026-05-31T10:05:01Z",
      "lat": 20.594,
      "lon": -100.391,
      "accuracy_m": 10
    }
  ]
}
```

#### Errores comunes

- `422 Unprocessable Entity`: faltan campos obligatorios o formato inválido.
- `503 Service Unavailable`: no se pudo publicar la ubicación en Kafka.

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
  "battery_level": 82
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
  "battery_level": 82
}
```

#### Errores comunes

- `422 Unprocessable Entity`: faltan campos obligatorios o formato inválido.
- `503 Service Unavailable`: no se pudo publicar la ubicación en Kafka.

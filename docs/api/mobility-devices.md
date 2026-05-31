# API de Dispositivos de Movilidad

## Descripción

Endpoint para registrar dispositivos de movilidad asociados al usuario autenticado.

La información se almacena en `mobility.devices` y permite vincular opcionalmente un dispositivo de notificaciones push (`user_devices.id`) mediante `notification_device_id`.

---

## Endpoints

### 1. Listar Dispositivos de Movilidad

**GET** `/api/v1/mobility/devices`

Lista los dispositivos del usuario autenticado.

#### Headers

```http
Authorization: Bearer <access_token>
```

#### Query Params (opcionales)

- `is_active` (boolean): filtra por estado activo/inactivo.
- `device_type` (string): filtra por tipo (`PHONE`, `WATCH`, `BLE_TAG`, `WEARABLE`).

#### Response 200 OK

```json
[
  {
    "id": "57479658-86f4-49b4-95eb-37f9d2d994d2",
    "user_id": "9a4a3dbf-5ba7-4550-8f14-89db1d58a8e8",
    "device_type": "PHONE",
    "platform": "android",
    "device_name": "Pixel 8",
    "external_device_id": "android-id-123",
    "app_version": "1.9.0",
    "os_version": "Android 15",
    "last_seen_at": "2026-05-30T17:10:44.215Z",
    "is_active": true,
    "metadata": {
      "manufacturer": "Google"
    },
    "created_at": "2026-05-30T17:10:44.215Z",
    "updated_at": "2026-05-30T17:10:44.215Z",
    "notification_device_id": "8f949f43-23dd-4a7b-9d7f-6e85017a7f80"
  }
]
```

#### Errores Comunes

- **401 Unauthorized**: token inválido o ausente.

---

### 2. Registrar Dispositivo de Movilidad

**POST** `/api/v1/mobility/devices`

Crea un registro de dispositivo para el usuario autenticado.

#### Headers

```http
Authorization: Bearer <access_token>
```

#### Request Body

```json
{
  "device_type": "PHONE",
  "platform": "android",
  "device_name": "Pixel 8",
  "external_device_id": "android-id-123",
  "app_version": "1.9.0",
  "os_version": "Android 15",
  "metadata": {
    "manufacturer": "Google"
  },
  "notification_device_id": "8f949f43-23dd-4a7b-9d7f-6e85017a7f80"
}
```

#### Campos

- `device_type` (string, requerido): tipo de dispositivo. Valores válidos: `PHONE`, `WATCH`, `BLE_TAG`, `WEARABLE`.
- `platform` (string, opcional): plataforma o sistema operativo.
- `device_name` (string, opcional): nombre descriptivo del equipo.
- `external_device_id` (string, opcional): identificador externo del dispositivo.
- `app_version` (string, opcional): versión de la app móvil.
- `os_version` (string, opcional): versión del sistema operativo.
- `last_seen_at` (datetime, opcional): última actividad reportada. Si no se envía, se usa la hora actual.
- `is_active` (boolean, opcional, default `true`): estado del dispositivo.
- `metadata` (objeto, opcional, default `{}`): información adicional libre en JSON.
- `notification_device_id` (uuid, opcional): ID de `user_devices` del mismo usuario.

#### Response 201 Created

```json
{
  "id": "57479658-86f4-49b4-95eb-37f9d2d994d2",
  "user_id": "9a4a3dbf-5ba7-4550-8f14-89db1d58a8e8",
  "device_type": "PHONE",
  "platform": "android",
  "device_name": "Pixel 8",
  "external_device_id": "android-id-123",
  "app_version": "1.9.0",
  "os_version": "Android 15",
  "last_seen_at": "2026-05-30T17:10:44.215Z",
  "is_active": true,
  "metadata": {
    "manufacturer": "Google"
  },
  "created_at": "2026-05-30T17:10:44.215Z",
  "updated_at": "2026-05-30T17:10:44.215Z",
  "notification_device_id": "8f949f43-23dd-4a7b-9d7f-6e85017a7f80"
}
```

#### Errores Comunes

- **401 Unauthorized**: token inválido o ausente.
- **404 Not Found**: `notification_device_id` no existe o no pertenece al usuario autenticado.
- **409 Conflict**: conflicto de integridad (por ejemplo, `notification_device_id` ya vinculado en otro registro).
- **422 Unprocessable Entity**: payload inválido (ej. `device_type` fuera del catálogo permitido).

---

## Notas Técnicas

- `user_id` siempre se resuelve desde el usuario autenticado; no se acepta en el request.
- Si se envía `notification_device_id`, se valida pertenencia al mismo usuario para evitar vinculaciones cruzadas.
- La unicidad de `notification_device_id` sigue la regla de BD (`UNIQUE WHERE notification_device_id IS NOT NULL`).

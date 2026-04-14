# API de Dispositivos de Usuario (Push)

## Descripción

Endpoints para registrar y desactivar dispositivos móviles de usuario usados en notificaciones push con AWS SNS.

Este módulo no administra GPS/IoT del inventario; solo tokens de dispositivos móviles asociados a usuarios.

---

## Endpoints

### 1. Registrar Dispositivo de Usuario

**POST** `/api/v1/user-devices/register`

Registra o actualiza un `device_token` para el usuario autenticado.

- Si no existe, crea registro nuevo y endpoint SNS.
- Si existe, lo reasigna al usuario actual, lo reactiva y actualiza `last_seen_at`.
- Si el endpoint SNS es inválido, se recrea automáticamente.

#### Headers

```http
Authorization: Bearer <access_token>
```

#### Request Body (register)

```json
{
  "device_token": "abc123",
  "platform": "ios"
}
```

#### Campos

- `device_token` (string, requerido): token del dispositivo móvil.
- `platform` (string, requerido): plataforma del dispositivo. Valores válidos: `ios`, `android`.

#### Response 200 OK (register)

```json
{
  "device_token": "abc123",
  "platform": "ios",
  "endpoint_arn": "arn:aws:sns:us-east-1:123456789012:endpoint/APNS/app/...",
  "is_active": true,
  "last_seen_at": "2026-04-12T20:00:00Z"
}
```

#### Errores Comunes (register)

- **401 Unauthorized**: token inválido o ausente.
- **422 Unprocessable Entity**: payload inválido (ej. `platform` fuera de `ios|android`).
- **503 Service Unavailable**: no fue posible registrar en SNS (configuración AWS/SNS incompleta).

---

### 2. Desactivar Dispositivo de Usuario

**POST** `/api/v1/user-devices/deactivate`

Marca el dispositivo como inactivo (`is_active=false`) para el `device_token` enviado.

**Auth:** No requiere token en la implementación actual.

#### Request Body (deactivate)

```json
{
  "device_token": "abc123"
}
```

#### Response 200 OK (deactivate)

```json
{
  "message": "Dispositivo desactivado exitosamente",
  "device_token": "abc123",
  "is_active": false
}
```

#### Errores Comunes (deactivate)

- **404 Not Found**: `device_token` no encontrado.
- **422 Unprocessable Entity**: payload inválido.

---

## Modelo de Datos

### UserDevice

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "device_token": "abc123",
  "platform": "ios",
  "endpoint_arn": "arn:aws:sns:...",
  "is_active": true,
  "last_seen_at": "2026-04-12T20:00:00Z",
  "updated_at": "2026-04-12T20:00:00Z"
}
```

## Notas Técnicas

- El registro usa `device_token` como clave lógica para upsert.
- `register` actualiza `last_seen_at` en cada llamada exitosa.
- `deactivate` no elimina filas; realiza actualización de estado.
- La creación/recuperación de endpoint SNS se resuelve en servicio (`get_or_recreate_endpoint`).

---

## Publicación de Eventos en Kafka

Al completar exitosamente las operaciones, se publica un evento en Kafka al tópico configurado por la variable de entorno `KAFKA_USER_DEVICES_UPDATES_TOPIC`.

Si el envío a Kafka falla, el endpoint **no falla**: se registra el error en logs y la respuesta HTTP se mantiene exitosa.

### Evento para altas/cambios (`register`)

```json
{
  "type": "UPSERT",
  "user_id": "uuid",
  "device_id": "string",
  "endpoint_arn": "arn:aws:sns:us-east-1:123456789012:endpoint/APNS/app/...",
  "unit_id": "uuid",
  "is_active": true,
  "updated_at": "2026-04-13T20:10:00Z"
}
```

### Evento para desactivación (`deactivate`)

```json
{
  "type": "DELETE",
  "user_id": "uuid",
  "device_id": "string",
  "endpoint_arn": "arn:aws:sns:us-east-1:123456789012:endpoint/APNS/app/...",
  "unit_id": "uuid",
  "is_active": false,
  "updated_at": "2026-04-13T20:10:00Z"
}

`unit_id` se toma de la asignación más reciente del usuario en `user_units`. Si el usuario no tiene unidades asignadas, se envía `null`.

`endpoint_arn` se publica con el valor almacenado en `user_devices.endpoint_arn` al momento del evento.

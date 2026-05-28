# API de User Commands

## Descripción

Endpoint para comandos de alto riesgo iniciados por usuario master sobre una unidad.

Actualmente soporta dos tipos de comando:

- ENGINE_STOP
- ENGINE_RESUME

El sistema resuelve automáticamente el dispositivo activo de la unidad, forma el payload AT para el equipo soportado y lo envía por KORE, registrando el comando en la tabla commands igual que el flujo de commands estándar.

---

## Endpoint

### Crear User Command

POST /api/v1/user-commands

### Listar User Commands por Unidad

GET /api/v1/user-commands/unit/{unit_id}

### Sincronizar User Command con KORE

POST /api/v1/user-commands/{command_id}/sync

---

## Autenticación y permisos

- Requiere autenticación Cognito.
- Solo usuario master puede ejecutar este endpoint.

Si el usuario no es master, responde 403.

---

## Por qué existen estos endpoints

Estos endpoints existen para separar comandos críticos de usuario (alto riesgo) del flujo genérico de commands.

Diferencias clave frente a /api/v1/commands:

- /api/v1/user-commands exige reglas de negocio para seguridad humana:
  - Validación de confirmation para ENGINE_STOP
  - Validación de contraseña del usuario master
  - Formación automática del comando AT según modelo
- /api/v1/user-commands/unit/{unit_id} permite consultar por unidad de negocio directamente.
- /api/v1/user-commands/{command_id}/sync asegura que solo se sincronicen comandos creados por user-commands (metadata.source_id = user_commands).
- /api/v1/commands mantiene el flujo genérico por device_id y no aplica estas reglas de alto riesgo.

---

## Request Body

```json
{
  "command_type": "ENGINE_RESUME",
  "unit_id": "f9d3f26f-5f4a-4a87-9873-8a7b1846f15f",
  "confirmation": {
    "accepted_risk": true,
    "password": "user-password"
  }
}
```

### Campos

| Campo | Tipo | Requerido | Descripción |
| ----- | ---- | --------- | ----------- |
| command_type | string | Sí | Tipo de comando. Valores: ENGINE_STOP, ENGINE_RESUME |
| unit_id | UUID | Sí | ID de la unidad objetivo |
| confirmation | object | Condicional | Requerido para ENGINE_STOP |
| confirmation.accepted_risk | bool | Condicional | Debe ser true para ENGINE_STOP |
| confirmation.password | string | Condicional | Contraseña del usuario master. Se valida en Cognito con el mismo mecanismo de login |

### Reglas de confirmation

- ENGINE_STOP:
  - confirmation es obligatorio
  - accepted_risk debe ser true
  - password debe ser válido
- ENGINE_RESUME:
  - confirmation no es obligatorio

---

## Formación de comando por modelo

La API toma command_type y unit_id, busca el dispositivo activo de la unidad y construye el comando según brand y model del dispositivo.

### Soporte actual

Se soportan equipos Suntech cuyo modelo cumpla:

- Empieza con ST4
- Sigue con exactamente 3 dígitos
- Puede tener sufijo opcional de letras

Patrón: ST4 + 3 dígitos + sufijo opcional

Regex exacta aplicada por la API:

```regex
^ST4\d{3}[A-Z]*$
```

Nota: la validación se realiza en mayúsculas internamente.

Ejemplos:

- ST4330: permitido
- ST4315: permitido
- ST4315U: permitido
- ST449: no permitido

| Equipo | command_type | Payload generado |
| ------ | ------------ | ---------------- |
| Suntech ST4xxx (+ sufijo opcional) | ENGINE_STOP | AT^CMD;[device_id];04;01 |
| Suntech ST4xxx (+ sufijo opcional) | ENGINE_RESUME | AT^CMD;[device_id];04;02 |

Si el equipo no está soportado, responde error explícito 422.

---

## Flujo interno

1. Valida usuario master.
2. Valida reglas de confirmation según command_type.
3. Valida password (solo ENGINE_STOP) contra Cognito.
4. Busca unidad por unit_id dentro de la organización del usuario.
5. Resuelve la asignación activa en unit_devices.
6. Obtiene el dispositivo y forma el comando AT según modelo.
7. Crea registro en commands con:
   - media = KORE_SMS_API
   - status inicial = pending
   - metadata con source_id=user_commands, command_type, unit_id
8. Busca kore_sim_id en unified_sim_profiles.
9. Intenta envío por KORE:
   - éxito: status = sent, guarda kore_response y kore_sim_id en metadata
   - error de KORE: conserva pending y guarda kore_error en metadata

---

## Response

### 201 Created

Misma estructura de respuesta que POST /api/v1/commands.

```json
{
  "command_id": "42bfcefb-4aa3-4866-b12b-7fa34b87f923",
  "status": "sent"
}
```

El status puede ser:

- sent: si se envió correctamente por KORE
- pending: si no se envió aún o hubo error de envío

---

## Endpoint: Listar User Commands por Unidad

GET /api/v1/user-commands/unit/{unit_id}

Retorna comandos creados desde user-commands para una unidad específica.

Filtros disponibles:

- status_filter: pending, sent, delivered, failed
- limit: 1..500 (default 50)
- offset: default 0

### Response 200 OK

Misma estructura base de listado de commands:

```json
{
  "commands": [
    {
      "command_id": "42bfcefb-4aa3-4866-b12b-7fa34b87f923",
      "command": "AT^CMD;353451234567890;04;01",
      "media": "KORE_SMS_API",
      "request_user_id": "def45678-e89b-12d3-a456-426614174000",
      "request_user_email": "usuario@ejemplo.com",
      "device_id": "353451234567890",
      "requested_at": "2026-05-27T10:30:00Z",
      "updated_at": "2026-05-27T10:31:00Z",
      "status": "sent",
      "command_metadata": {
        "source_id": "user_commands",
        "command_type": "ENGINE_STOP",
        "unit_id": "f9d3f26f-5f4a-4a87-9873-8a7b1846f15f"
      }
    }
  ],
  "total": 1
}
```

---

## Endpoint: Sincronizar User Command con KORE

POST /api/v1/user-commands/{command_id}/sync

Sincroniza el estado del comando en KORE solo si fue creado por user-commands.

Reglas:

- Debe existir metadata.source_id = user_commands
- Debe ser media KORE_SMS_API
- Debe existir metadata.kore_response con sid/url

### Response 200 OK

Misma estructura de sync que commands:

```json
{
  "command_id": "42bfcefb-4aa3-4866-b12b-7fa34b87f923",
  "command": "AT^CMD;353451234567890;04;01",
  "media": "KORE_SMS_API",
  "request_user_id": "def45678-e89b-12d3-a456-426614174000",
  "request_user_email": "usuario@ejemplo.com",
  "device_id": "353451234567890",
  "requested_at": "2026-05-27T10:30:00Z",
  "updated_at": "2026-05-27T10:35:00Z",
  "status": "delivered",
  "command_metadata": {
    "source_id": "user_commands",
    "sync_response": {
      "status": "delivered"
    }
  },
  "sync_response": {
    "status": "delivered"
  }
}
```

---

## Errores

| Código | Caso |
| ------ | ---- |
| 400 | ENGINE_STOP sin confirmation |
| 400 | accepted_risk distinto de true para ENGINE_STOP |
| 400 | Dispositivo sin SIM KORE configurada |
| 401 | Contraseña inválida |
| 403 | Usuario no master |
| 404 | Unidad no encontrada |
| 404 | Comando user-command no encontrado |
| 404 | Unidad sin dispositivo asignado activo |
| 404 | Dispositivo no encontrado para la unidad |
| 422 | No se pudo formar comando para el modelo del equipo |
| 500 | Error al validar contraseña con Cognito |

---

## Ejemplos

### ENGINE_STOP con confirmation

```bash
curl -X POST "http://localhost:8000/api/v1/user-commands" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "command_type": "ENGINE_STOP",
    "unit_id": "f9d3f26f-5f4a-4a87-9873-8a7b1846f15f",
    "confirmation": {
      "accepted_risk": true,
      "password": "my-password"
    }
  }'
```

### ENGINE_RESUME sin confirmation

```bash
curl -X POST "http://localhost:8000/api/v1/user-commands" \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "command_type": "ENGINE_RESUME",
    "unit_id": "f9d3f26f-5f4a-4a87-9873-8a7b1846f15f"
  }'
```

### Listar comandos user-commands por unidad

```bash
curl -X GET "http://localhost:8000/api/v1/user-commands/unit/f9d3f26f-5f4a-4a87-9873-8a7b1846f15f?status_filter=sent&limit=20&offset=0" \
  -H "Authorization: Bearer <access_token>"
```

### Sincronizar user-command con KORE

```bash
curl -X POST "http://localhost:8000/api/v1/user-commands/42bfcefb-4aa3-4866-b12b-7fa34b87f923/sync" \
  -H "Authorization: Bearer <access_token>"
```

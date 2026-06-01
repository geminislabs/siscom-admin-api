# API de Comandos

## Descripción

Endpoints para gestionar comandos enviados a dispositivos GPS/IoT. Permite crear comandos, consultar su estado y obtener el historial de comandos por dispositivo.

> Nota: Para comandos críticos iniciados por usuario master sobre unidades (ENGINE_STOP/ENGINE_RESUME con reglas de confirmation y password), usar `/api/v1/user-commands`. Ver [API de User Commands](./user-commands.md).

---

## ⚠️ ADVERTENCIA DE SEGURIDAD

> **IMPORTANTE:** Este endpoint utiliza el campo `email` del token de autenticación para identificar al usuario que crea el comando (`request_user_email`).
>
> **Para mantener la seguridad del sistema:**
> - **NUNCA** exponer públicamente aplicaciones como `gac-admin` u otros servicios que generen tokens PASETO
> - El endpoint `POST /api/v1/auth/internal` debe estar protegido por firewall, VPN o API Gateway
> - Los tokens PASETO contienen el email del usuario, si se compromete un token, se puede suplantar la identidad
> - Solo servicios internos de confianza deben tener acceso a la generación de tokens

---

## Modelo de Datos

### Command

```json
{
  "command_id": "42bfcefb-4aa3-4866-b12b-7fa34b87f923",
  "template_id": "abc12345-e89b-12d3-a456-426614174000",
  "command": "AT+LOCATION",
  "media": "sms",
  "request_user_id": "def45678-e89b-12d3-a456-426614174000",
  "request_user_email": "usuario@ejemplo.com",
  "device_id": "353451234567890",
  "requested_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:35:00Z",
  "status": "delivered",
  "metadata": {
    "source_id": "mobile_app",
    "response_raw": "OK"
  }
}
```

---

## Estados del Comando

El campo `status` representa el estado actual del comando en su ciclo de vida:

| Estado      | Descripción                                          |
| ----------- | ---------------------------------------------------- |
| `pending`   | Comando creado, pendiente de envío                   |
| `sent`      | Comando enviado al dispositivo                       |
| `delivered` | Comando entregado/confirmado por el dispositivo      |
| `failed`    | Comando falló en el envío o ejecución                |

---

## Campos del Modelo

| Campo               | Tipo      | Requerido | Descripción                                      |
| ------------------- | --------- | --------- | ------------------------------------------------ |
| `command_id`        | UUID      | Auto      | Identificador único del comando (generado)       |
| `template_id`       | UUID      | No        | Referencia al template de comando usado          |
| `command`           | TEXT      | Sí        | El comando a enviar al dispositivo               |
| `media`             | TEXT      | Sí        | Medio de comunicación (sms, tcp, etc.)           |
| `request_user_id`   | UUID      | No        | UUID del usuario (solo con token Cognito)        |
| `request_user_email`| TEXT      | Auto      | Email del usuario que creó el comando (del token)|
| `device_id`         | TEXT      | Sí        | ID del dispositivo destino                       |
| `requested_at`      | TIMESTAMP | Auto      | Fecha/hora de creación del comando               |
| `updated_at`        | TIMESTAMP | Auto      | Fecha/hora de última actualización               |
| `status`            | TEXT      | Auto      | Estado actual del comando                        |
| `metadata`          | JSONB     | No        | Datos adicionales (source_id, response_raw, etc.)|

---

## Endpoints

### 1. Crear Comando

**POST** `/api/v1/commands`

Crea un nuevo comando para enviar a un dispositivo.

**Comportamiento con KORE Wireless:**
- Si el dispositivo tiene una SIM con `kore_sim_id` configurado en la vista `unified_sim_profiles`, el comando se enviará automáticamente vía KORE SMS.
- Si el envío KORE es exitoso, el estado será `sent`.
- Si no hay SIM KORE configurada o el envío falla, el estado será `pending`.
- Los detalles del envío KORE se guardan en `metadata.kore_response` o `metadata.kore_error`.

> Ver [Guía de Integración KORE](../guides/kore-integration.md) para más detalles.

#### Headers

```
Authorization: Bearer <access_token>
```

#### Request Body

```json
{
  "command": "AT+LOCATION",
  "media": "sms",
  "device_id": "353451234567890",
  "template_id": "abc12345-e89b-12d3-a456-426614174000",
  "metadata": {
    "source_id": "mobile_app"
  }
}
```

#### Campos del Request

| Campo         | Tipo   | Requerido | Descripción                                |
| ------------- | ------ | --------- | ------------------------------------------ |
| `command`     | string | Sí        | El comando a enviar al dispositivo         |
| `media`       | string | Sí        | Medio de comunicación (sms, tcp, etc.)     |
| `device_id`   | string | Sí        | ID del dispositivo destino                 |
| `template_id` | UUID   | No        | ID del template de comando (opcional)      |
| `metadata`    | object | No        | Datos adicionales del comando (opcional)   |

#### Validaciones

- El `device_id` debe existir en la tabla de dispositivos
- El usuario debe estar autenticado (se obtiene `request_user_id` del token)

#### Response 201 Created

**Sin integración KORE o sin kore_sim_id:**
```json
{
  "command_id": "42bfcefb-4aa3-4866-b12b-7fa34b87f923",
  "status": "pending"
}
```

**Con integración KORE exitosa:**
```json
{
  "command_id": "42bfcefb-4aa3-4866-b12b-7fa34b87f923",
  "status": "sent"
}
```

#### Errores

| Código | Descripción                           |
| ------ | ------------------------------------- |
| 401    | No autorizado (token inválido)        |
| 404    | Dispositivo no encontrado             |
| 422    | Datos de entrada inválidos            |

---

### 2. Listar Comandos por Dispositivo

**GET** `/api/v1/commands/device/{device_id}`

Obtiene todos los comandos enviados a un dispositivo específico, con soporte para filtrado y paginación.

#### Headers

```
Authorization: Bearer <access_token>
```

#### Path Parameters

| Parámetro   | Tipo   | Descripción                      |
| ----------- | ------ | -------------------------------- |
| `device_id` | string | ID del dispositivo a consultar   |

#### Query Parameters

| Parámetro       | Tipo   | Default | Descripción                                           |
| --------------- | ------ | ------- | ----------------------------------------------------- |
| `status_filter` | string | -       | Filtrar por estado (pending, sent, delivered, failed) |
| `limit`         | int    | 50      | Límite de resultados (1-500)                          |
| `offset`        | int    | 0       | Offset para paginación                                |

#### Response 200 OK

```json
{
  "commands": [
    {
      "command_id": "42bfcefb-4aa3-4866-b12b-7fa34b87f923",
      "template_id": "abc12345-e89b-12d3-a456-426614174000",
      "command": "AT+LOCATION",
      "media": "sms",
      "request_user_id": "def45678-e89b-12d3-a456-426614174000",
      "device_id": "353451234567890",
      "requested_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:35:00Z",
      "status": "delivered",
      "metadata": {
        "source_id": "mobile_app",
        "response_raw": "OK"
      }
    },
    {
      "command_id": "53cfdefb-5bb4-5977-c23c-8gb45c98g034",
      "template_id": null,
      "command": "AT+RESTART",
      "media": "tcp",
      "request_user_id": "def45678-e89b-12d3-a456-426614174000",
      "device_id": "353451234567890",
      "requested_at": "2024-01-14T15:00:00Z",
      "updated_at": "2024-01-14T15:00:00Z",
      "status": "pending",
      "metadata": null
    }
  ],
  "total": 25
}
```

#### Ejemplos

```bash
# Todos los comandos de un dispositivo
GET /api/v1/commands/device/353451234567890

# Solo comandos pendientes
GET /api/v1/commands/device/353451234567890?status_filter=pending

# Con paginación
GET /api/v1/commands/device/353451234567890?limit=10&offset=20

# Comandos fallidos
GET /api/v1/commands/device/353451234567890?status_filter=failed
```

#### Errores

| Código | Descripción                                                        |
| ------ | ------------------------------------------------------------------ |
| 400    | Estado inválido (status_filter no es pending/sent/delivered/failed)|
| 401    | No autorizado (token inválido)                                     |
| 404    | Dispositivo no encontrado                                          |

---

### 3. Obtener Comando por ID

**GET** `/api/v1/commands/{command_id}`

Obtiene el detalle completo de un comando específico por su UUID.

#### Headers

```
Authorization: Bearer <access_token>
```

#### Path Parameters

| Parámetro    | Tipo | Descripción                  |
| ------------ | ---- | ---------------------------- |
| `command_id` | UUID | ID único del comando         |

#### Response 200 OK

```json
{
  "command_id": "42bfcefb-4aa3-4866-b12b-7fa34b87f923",
  "template_id": "abc12345-e89b-12d3-a456-426614174000",
  "command": "AT+LOCATION",
  "media": "sms",
  "request_user_id": "def45678-e89b-12d3-a456-426614174000",
  "device_id": "353451234567890",
  "requested_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:35:00Z",
  "status": "delivered",
  "metadata": {
    "source_id": "mobile_app",
    "response_raw": "OK"
  }
}
```

#### Errores

| Código | Descripción                     |
| ------ | ------------------------------- |
| 401    | No autorizado (token inválido)  |
| 404    | Comando no encontrado           |

---

### 4. Sincronizar Comando con KORE

**POST** `/api/v1/commands/{command_id}/sync`

Sincroniza el estado de un comando SMS con KORE Wireless, consultando el estado actual del mensaje en la plataforma.

**Comportamiento:**
- Solo soporta comandos con `media="KORE_SMS_API"`
- Extrae la URL del SMS desde `metadata.kore_response.url`
- Se autentica automáticamente con KORE si no hay sesión activa
- Actualiza el `metadata` del comando con la respuesta de sincronización
- **Actualiza el `status` del comando** con el valor de `status` del response de KORE (ej: `queued`, `sent`, `delivered`, `failed`)
- Si el token de KORE expira durante la consulta, re-autentica automáticamente

#### Headers

```
Authorization: Bearer <access_token>
```

#### Path Parameters

| Parámetro    | Tipo | Descripción                      |
| ------------ | ---- | -------------------------------- |
| `command_id` | UUID | ID único del comando a sincronizar |

#### Response 200 OK

```json
{
  "command_id": "42bfcefb-4aa3-4866-b12b-7fa34b87f923",
  "template_id": "abc12345-e89b-12d3-a456-426614174000",
  "command": "AT^PRG;0848028047;10;81#001F803F",
  "media": "KORE_SMS_API",
  "request_user_id": "def45678-e89b-12d3-a456-426614174000",
  "request_user_email": "usuario@ejemplo.com",
  "device_id": "353451234567890",
  "requested_at": "2025-12-16T04:29:00Z",
  "updated_at": "2025-12-16T04:30:15Z",
  "status": "delivered",
  "command_metadata": {
    "kore_sim_id": "FAKE_SIM_ID",
    "kore_response": {
      "sid": "FAKE_SID",
      "url": "https://supersim.api.korewireless.com/v1/SmsCommands/FAKE_SID",
      "status": "queued"
    },
    "sync_response": {
      "account_sid": "SOME",
      "sid": "FAKE_SID",
      "payload": "AT^PRG;0848028047;10;81#001F803F",
      "sim_sid": "FAKE_SIM_ID",
      "direction": "to_sim",
      "status": "delivered",
      "date_created": "2025-12-16T04:29:21Z",
      "date_updated": "2025-12-16T04:30:11Z",
      "url": "https://supersim.api.korewireless.com/v1/SmsCommands/FAKE_SID"
    }
  }
}
```

#### Campos de la Respuesta

| Campo              | Tipo   | Descripción                                              |
| ------------------ | ------ | -------------------------------------------------------- |
| `command_id`       | UUID   | ID único del comando                                     |
| `template_id`      | UUID   | Referencia al template de comando (opcional)             |
| `command`          | string | El comando enviado al dispositivo                        |
| `media`            | string | Medio de comunicación (KORE_SMS_API)                     |
| `request_user_id`  | UUID   | UUID del usuario que creó el comando                     |
| `request_user_email`| string| Email del usuario que creó el comando                    |
| `device_id`        | string | ID del dispositivo destino                               |
| `requested_at`     | string | Fecha/hora de creación del comando                       |
| `updated_at`       | string | Fecha/hora de última actualización                       |
| `status`           | string | Estado actual del comando                                |
| `command_metadata` | object | Metadata del comando (incluye sync_response guardado)    |
| `sync_response`    | object | Respuesta de la consulta de sincronización a KORE        |

#### Errores

| Código | Descripción                                                     |
| ------ | --------------------------------------------------------------- |
| 400    | Metadata faltante, kore_response faltante, o sid/url faltantes  |
| 401    | No autorizado (token inválido)                                  |
| 404    | Comando no encontrado                                           |
| 501    | Media no soportado (diferente a KORE_SMS_API)                   |

#### Ejemplo de Uso

```bash
# Sincronizar estado de un comando con KORE
POST /api/v1/commands/42bfcefb-4aa3-4866-b12b-7fa34b87f923/sync
Authorization: Bearer <token>
```

#### Estructura de Metadata después de Sync

```json
{
  "kore_sim_id": "FAKE_SIM_ID",
  "kore_response": {
    "sid": "FAKE_SID",
    "url": "https://supersim.api.korewireless.com/v1/SmsCommands/FAKE_SID",
    "status": "queued"
  },
  "sync_response": {
    "account_sid": "SOME",
    "sid": "FAKE_SID",
    "payload": "AT^PRG;0848028047;10;81#001F803F",
    "sim_sid": "FAKE_SIM_ID",
    "direction": "to_sim",
    "status": "delivered",
    "date_created": "2025-12-16T04:29:21Z",
    "date_updated": "2025-12-16T04:30:11Z",
    "url": "https://supersim.api.korewireless.com/v1/SmsCommands/FAKE_SID"
  }
}
```

#### Campos del sync_response de KORE

| Campo         | Tipo   | Descripción                                              |
| ------------- | ------ | -------------------------------------------------------- |
| `account_sid` | string | ID de la cuenta en KORE                                  |
| `sid`         | string | ID único del comando SMS en KORE                         |
| `payload`     | string | Contenido del comando enviado                            |
| `sim_sid`     | string | ID de la SIM en KORE                                     |
| `direction`   | string | Dirección del mensaje (`to_sim` = hacia el dispositivo)  |
| `status`      | string | Estado del SMS (`queued`, `sent`, `delivered`, `failed`) |
| `date_created`| string | Fecha/hora de creación del SMS en KORE                   |
| `date_updated`| string | Fecha/hora de última actualización del estado            |
| `url`         | string | URL del recurso en la API de KORE                        |

> **Nota:** Si ocurre un error durante la sincronización, se guardará en `metadata.sync_error` y también se incluirá en la respuesta.

---

## Flujo de Uso Típico

```
1. CREAR COMANDO
   POST /api/v1/commands
   → status='pending', command_id=<uuid>
   → Si tiene kore_sim_id: status='sent', metadata.kore_response con sid y url

2. SISTEMA EXTERNO PROCESA
   (El servicio de mensajería actualiza el estado)
   → status='sent' cuando se envía
   → status='delivered' cuando se confirma
   → status='failed' si falla

3. SINCRONIZAR CON KORE (opcional, solo para KORE_SMS_API)
   POST /api/v1/commands/{command_id}/sync
   → Consulta estado actual en KORE
   → Actualiza metadata.sync_response
   → Actualiza command.status con el status de KORE
   → Retorna sync_response con el estado actual

4. CONSULTAR ESTADO
   GET /api/v1/commands/{command_id}
   → Ver estado actual y metadata

5. HISTORIAL POR DISPOSITIVO
   GET /api/v1/commands/device/{device_id}
   → Ver todos los comandos del dispositivo
```

---

## Ejemplos Completos

### Caso 1: Enviar Comando de Ubicación

```bash
# Crear comando
POST /api/v1/commands
Authorization: Bearer <token>
Content-Type: application/json

{
  "command": "AT+GTGPS",
  "media": "sms",
  "device_id": "353451234567890",
  "metadata": {
    "source_id": "web_dashboard",
    "priority": "high"
  }
}

# Respuesta
{
  "command_id": "42bfcefb-4aa3-4866-b12b-7fa34b87f923",
  "status": "pending"
}

# Verificar estado después
GET /api/v1/commands/42bfcefb-4aa3-4866-b12b-7fa34b87f923
```

### Caso 2: Consultar Historial de Comandos

```bash
# Ver últimos 10 comandos del dispositivo
GET /api/v1/commands/device/353451234567890?limit=10

# Ver solo comandos fallidos
GET /api/v1/commands/device/353451234567890?status_filter=failed

# Paginar resultados (página 3 de 10 elementos)
GET /api/v1/commands/device/353451234567890?limit=10&offset=20
```

### Caso 3: Comando con Template

```bash
# Crear comando usando un template predefinido
POST /api/v1/commands
{
  "command": "AT+GTOUT=gv300,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0$",
  "media": "tcp",
  "device_id": "353451234567890",
  "template_id": "abc12345-e89b-12d3-a456-426614174000",
  "metadata": {
    "template_name": "output_control",
    "output_number": 1
  }
}
```

---

## Estructura de Metadata

El campo `metadata` es flexible (JSONB) y puede contener información adicional según el caso de uso:

### Ejemplos de Metadata

```json
// Al crear el comando
{
  "source_id": "mobile_app",
  "priority": "high",
  "retry_count": 0
}

// Después de procesar
{
  "source_id": "mobile_app",
  "priority": "high",
  "retry_count": 2,
  "response_raw": "OK",
  "delivered_at": "2024-01-15T10:35:00Z",
  "delivery_channel": "sms_gateway"
}

// En caso de fallo
{
  "source_id": "mobile_app",
  "priority": "high",
  "retry_count": 3,
  "error_code": "DEVICE_OFFLINE",
  "error_message": "Device did not respond after 3 attempts",
  "last_attempt_at": "2024-01-15T10:45:00Z"
}

// Con integración KORE (envío exitoso)
{
  "source_id": "web_dashboard",
  "kore_sim_id": "HS0ad6bc269850dfe13bc8bddfcf8399f4",
  "kore_response": {
    "sid": "SMxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "status": "queued"
  }
}

// Con integración KORE (error)
{
  "source_id": "web_dashboard",
  "kore_error": "Error de autenticación KORE: 401 Unauthorized"
}
```

---

## Consideraciones de Seguridad

### Autenticación

- Todos los endpoints soportan autenticación dual:
  - **Token Cognito**: Para usuarios autenticados del sistema
  - **Token PASETO**: Para servicios internos (requiere `service="gac"` y `role="NEXUS_ADMIN"`)
- El `request_user_id` se obtiene del token Cognito, o del payload PASETO si está disponible
- Para obtener un token PASETO, usar `POST /api/v1/auth/internal`

### Auditoría

- Cada comando registra quién lo creó (`request_user_id`)
- Timestamps automáticos (`requested_at`, `updated_at`)
- El historial de comandos es inmutable (no se pueden eliminar)

### Validaciones

- El dispositivo debe existir en el sistema
- Los estados están controlados por CHECK constraint en la base de datos

---

## Consultas Útiles

```bash
# Comandos pendientes de un dispositivo
GET /api/v1/commands/device/353451234567890?status_filter=pending

# Comandos entregados exitosamente
GET /api/v1/commands/device/353451234567890?status_filter=delivered

# Comandos fallidos (para reintentar)
GET /api/v1/commands/device/353451234567890?status_filter=failed

# Últimos 100 comandos de un dispositivo
GET /api/v1/commands/device/353451234567890?limit=100

# Estado de un comando específico
GET /api/v1/commands/42bfcefb-4aa3-4866-b12b-7fa34b87f923

# Sincronizar estado de comando KORE SMS
POST /api/v1/commands/42bfcefb-4aa3-4866-b12b-7fa34b87f923/sync
```

---

## Tabla SQL de Referencia

```sql
CREATE TABLE commands (
    command_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id     UUID REFERENCES command_templates(template_id),
    command         TEXT NOT NULL,
    media           TEXT NOT NULL,
    request_user_id UUID NOT NULL,
    device_id       TEXT NOT NULL REFERENCES devices(device_id),
    requested_at    TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'pending',
    metadata        JSONB,
    
    CONSTRAINT check_command_status 
        CHECK (status IN ('pending', 'sent', 'delivered', 'failed'))
);

-- Índices para optimización
CREATE INDEX idx_commands_device_id ON commands(device_id);
CREATE INDEX idx_commands_request_user_id ON commands(request_user_id);
CREATE INDEX idx_commands_status ON commands(status);
CREATE INDEX idx_commands_requested_at ON commands(requested_at);
```

# Módulo: Commands

## 📌 Descripción

Envío y gestión de comandos a dispositivos GPS.
Permite enviar comandos SMS a dispositivos a través de la API de KORE Wireless (SuperSIM).

---

## 👤 Actor

- Usuario autenticado (via Cognito)
- Servicio interno (via PASETO con service="gac", role="NEXUS_ADMIN")

---

## 🔌 APIs Consumidas

### 🔹 KORE Wireless API (IoT/SMS Gateway)

| Endpoint | Método | Uso |
|----------|--------|-----|
| `KORE_API_AUTH` | POST | Autenticación OAuth2 (client_credentials) |
| `KORE_API_SMS` | POST | Envío de comando SMS a dispositivo |
| `{kore_response.url}` | GET | Sincronizar estado del SMS enviado |

**Autenticación:** OAuth2 Client Credentials

**Request de autenticación:**
```
POST {KORE_API_AUTH}
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
client_id={KORE_CLIENT_ID}
client_secret={KORE_CLIENT_SECRET}
```

**Request de envío SMS:**
```
POST {KORE_API_SMS}
Authorization: Bearer {access_token}
Content-Type: application/x-www-form-urlencoded

Sim={kore_sim_id}
Payload={command}
```

**Configuración requerida:**
- `KORE_CLIENT_ID`
- `KORE_CLIENT_SECRET`
- `KORE_API` (base para recursos SuperSIM, por ejemplo `{KORE_API}Sims`)
- `KORE_API_AUTH`
- `KORE_API_SMS`

---

### 🔹 PostgreSQL (Base de datos)

| Tabla | Operación | Uso |
|-------|-----------|-----|
| `commands` | INSERT | Registrar nuevo comando |
| `commands` | SELECT | Listar comandos por dispositivo |
| `commands` | UPDATE | Actualizar estado y metadata |
| `devices` | SELECT | Verificar existencia del dispositivo |
| `unified_sim_profiles` (vista) | SELECT | Obtener kore_sim_id del dispositivo |

---

## 🔁 Flujo funcional

### Crear Comando (`POST /commands`)

```
1. Valida autenticación (Cognito o PASETO)
2. Verifica que el dispositivo existe
3. Extrae email del usuario/servicio
4. Crea registro de comando (status: "pending")
5. Si KORE está configurado:
   a. Consulta unified_sim_profiles para obtener kore_sim_id
   b. Si tiene kore_sim_id:
      i. Autentica con KORE
      ii. Envía SMS con el comando
      iii. Actualiza status a "sent" si exitoso
      iv. Guarda metadata de respuesta KORE
6. Retorna command_id y status
```

### Listar Comandos por Dispositivo (`GET /commands/device/{device_id}`)

```
1. Valida autenticación
2. Verifica que el dispositivo existe
3. Filtra por status (opcional)
4. Aplica paginación (offset/limit)
5. Retorna lista de comandos con total
```

### Obtener Comando (`GET /commands/{command_id}`)

```
1. Valida autenticación
2. Busca comando por UUID
3. Retorna detalle completo del comando
```

### Sincronizar Comando (`POST /commands/{command_id}/sync`)

```
1. Valida autenticación
2. Busca comando en BD
3. Verifica que media sea "KORE_SMS_API"
4. Extrae URL de kore_response en metadata
5. Autentica con KORE (si no hay token cacheado)
6. GET a la URL de KORE para obtener estado
7. Actualiza metadata con sync_response
8. Actualiza status del comando si viene en respuesta
9. Retorna comando con sync_response
```

---

## ⚠️ Consideraciones

- El servicio KORE es **opcional** - si no está configurado, los comandos quedan en "pending"
- El `kore_sim_id` se obtiene de la vista `unified_sim_profiles`
- El token de KORE se cachea para evitar múltiples autenticaciones
- Si el token expira durante sync, se re-autentica automáticamente
- La sincronización solo soporta comandos con `media="KORE_SMS_API"`
- Los errores de KORE se guardan en `command_metadata.kore_error`

---

## 🔐 Autenticación Dual

Este módulo acepta dos tipos de autenticación:

| Tipo | Validación | Uso típico |
|------|------------|------------|
| **Cognito** | JWT válido con cognito_sub | Usuarios del panel web |
| **PASETO** | service="gac", role="NEXUS_ADMIN" | Servicios internos (GAC) |

El email del solicitante se extrae del payload del token correspondiente.

---

## 📊 Estados de Comando

| Status | Descripción |
|--------|-------------|
| `pending` | Comando creado, pendiente de envío |
| `sent` | Comando enviado exitosamente via KORE |
| `delivered` | SMS entregado al dispositivo (reportado por KORE) |
| `failed` | Error al enviar el comando |

---

## 📦 Estructura de Metadata

```json
{
  "kore_sim_id": "HSxxxxx",
  "kore_response": {
    "sid": "SMxxxxx",
    "url": "https://api.kore.com/...",
    "status": "sent"
  },
  "kore_error": "Error message (si hubo error)",
  "sync_response": {
    "status": "delivered",
    "...": "..."
  },
  "sync_error": "Error durante sync (si hubo)"
}
```

---

## 🧭 Relación C4 (preview)

- **Container:** SISCOM Admin API (FastAPI)
- **Consumes:** KORE Wireless API, PostgreSQL
- **Consumed by:** Web App, GAC Service (via PASETO)



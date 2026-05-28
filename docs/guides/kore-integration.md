# Integración con KORE Wireless

Este documento describe la integración con la API de KORE Wireless para el envío de comandos SMS a dispositivos con tarjetas SIM SuperSIM.

## Descripción General

KORE Wireless proporciona servicios de conectividad IoT a través de su plataforma SuperSIM. Esta integración permite enviar comandos a dispositivos GPS de forma automática cuando se crea un nuevo comando en el sistema.

## Configuración

### Variables de Entorno

Agregar las siguientes variables al archivo `.env`:

```bash
# KORE Wireless Configuration
KORE_CLIENT_ID=apiclient_xxxxxxxxxxxxxxxxxxxx
KORE_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KORE_API=https://supersim.api.korewireless.com/v1/
KORE_API_AUTH=https://api.korewireless.com/api-services/v1/auth/token
KORE_API_SMS=https://supersim.api.korewireless.com/v1/SmsCommands
```

| Variable | Descripción |
|----------|-------------|
| `KORE_CLIENT_ID` | ID del cliente API proporcionado por KORE |
| `KORE_CLIENT_SECRET` | Secret del cliente API proporcionado por KORE |
| `KORE_API` | URL base de SuperSIM API (se usa para construir rutas como `/Sims`) |
| `KORE_API_AUTH` | URL del endpoint de autenticación OAuth2 |
| `KORE_API_SMS` | URL del endpoint para envío de comandos SMS |

### Construcción de endpoints desde `KORE_API`

La integración usa `KORE_API` como base común para futuros recursos de KORE.

- Base: `https://supersim.api.korewireless.com/v1/`
- Recurso SIMs: `{KORE_API}Sims`

Esto evita agregar una variable nueva por cada recurso y facilita escalar la integración.

### Vista de Base de Datos

La integración utiliza la vista `unified_sim_profiles` que combina información de `sim_cards` y `sim_kore_profiles`:

```sql
CREATE VIEW unified_sim_profiles AS
SELECT 
    sc.sim_id,
    sc.device_id,
    sc.carrier,
    sc.iccid,
    sc.msisdn,
    sc.imsi,
    sc.status,
    sk.kore_sim_id,
    sc.metadata
FROM sim_cards sc
LEFT JOIN sim_kore_profiles sk ON sc.sim_id = sk.sim_id;
```

Para que un dispositivo pueda recibir comandos vía KORE, debe tener:
1. Un registro en `sim_cards` con el `device_id` correspondiente
2. Un registro en `sim_kore_profiles` con el `kore_sim_id` proporcionado por KORE

## Arquitectura

### Servicio KORE (`app/services/kore.py`)

El servicio proporciona dos métodos principales:

#### `authenticate()`

Obtiene un token de acceso usando OAuth2 con `client_credentials`:

```python
from app.services.kore import kore_service

# Autenticar
auth_response = await kore_service.authenticate()
print(f"Token: {auth_response.access_token}")
print(f"Expira en: {auth_response.expires_in} segundos")
```

**Respuesta:**
```python
@dataclass
class KoreAuthResponse:
    access_token: str   # Token JWT para autorización
    expires_in: int     # Tiempo de expiración en segundos
    token_type: str     # Tipo de token (Bearer)
    scope: str          # Alcance del token
```

#### `send_sms_command()`

Envía un comando SMS a un dispositivo:

```python
from app.services.kore import kore_service

# Enviar comando
response = await kore_service.send_sms_command(
    kore_sim_id="HS0ad6bc269850dfe13bc8bddfcf8399f4",
    payload="AT^PRG;0848028047;10;81#001F803F",
    access_token=auth_response.access_token
)

if response.success:
    print("Comando enviado exitosamente")
else:
    print(f"Error: {response.message}")
```

#### `send_command()` (Método conveniente)

Realiza autenticación y envío en un solo paso:

```python
response = await kore_service.send_command(
    kore_sim_id="HS0ad6bc269850dfe13bc8bddfcf8399f4",
    command="AT^PRG;0848028047;10;81#001F803F"
)
```

### Modelo UnifiedSimProfile (`app/models/unified_sim_profile.py`)

Modelo de solo lectura para la vista `unified_sim_profiles`:

```python
from app.models.unified_sim_profile import UnifiedSimProfile

# Consultar perfil de SIM para un dispositivo
sim_profile = db.query(UnifiedSimProfile).filter(
    UnifiedSimProfile.device_id == "DEV001"
).first()

if sim_profile and sim_profile.kore_sim_id:
    # El dispositivo tiene SIM KORE configurada
    print(f"KORE SIM ID: {sim_profile.kore_sim_id}")
```

## Sincronización de SIMs desde KORE

Existe un endpoint dedicado para sincronizar SIMs de KORE con las tablas locales:

- `POST /api/v1/sims/sync/kore`

Comportamiento:

1. Autentica contra KORE.
2. Consulta SIMs en `{KORE_API}Sims` con paginación.
3. Usa `sid` de KORE como `kore_sim_id` en `sim_kore_profiles`.
4. Inserta o actualiza `sim_cards` por `iccid`.
5. Inserta o actualiza `sim_kore_profiles` por `sim_id`.

## Flujo de Envío de Comandos

Cuando se crea un nuevo comando via `POST /api/v1/commands`:

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────┐
│  POST /commands │────▶│ Crear Command BD │────▶│ Consultar SIM  │
└─────────────────┘     └──────────────────┘     └────────────────┘
                                                         │
                                                         ▼
                                               ┌────────────────────┐
                                               │ ¿kore_sim_id != null? │
                                               └────────────────────┘
                                                    │         │
                                                   Sí        No
                                                    │         │
                                                    ▼         │
                                          ┌─────────────────┐ │
                                          │ Auth con KORE   │ │
                                          └─────────────────┘ │
                                                    │         │
                                                    ▼         │
                                          ┌─────────────────┐ │
                                          │ Enviar SMS KORE │ │
                                          └─────────────────┘ │
                                                    │         │
                                                    ▼         ▼
                                          ┌──────────────────────┐
                                          │ Actualizar status    │
                                          │ y metadata del cmd   │
                                          └──────────────────────┘
                                                    │
                                                    ▼
                                          ┌──────────────────────┐
                                          │ Retornar respuesta   │
                                          └──────────────────────┘
```

### Estados del Comando

| Estado | Descripción |
|--------|-------------|
| `pending` | Comando creado, no enviado vía KORE (SIM no configurada o error) |
| `sent` | Comando enviado exitosamente vía KORE SMS |
| `delivered` | Comando entregado/confirmado por el dispositivo |
| `failed` | Comando falló en el envío o ejecución |

### Metadata del Comando

Después del envío, el campo `command_metadata` puede contener:

```json
{
  "kore_sim_id": "HS0ad6bc269850dfe13bc8bddfcf8399f4",
  "kore_response": { /* respuesta de KORE API */ },
  "kore_error": "Error message si falló"
}
```

## Manejo de Errores

### Excepciones

| Excepción | Descripción |
|-----------|-------------|
| `KoreAuthError` | Error en la autenticación con KORE |
| `KoreSmsError` | Error al enviar SMS |
| `KoreServiceError` | Excepción base para errores de KORE |

### Comportamiento ante Errores

- Si KORE no está configurado, el comando se guarda con status `pending`
- Si la autenticación falla, el error se registra en `command_metadata.kore_error`
- Si el envío SMS falla, el error se registra en `command_metadata.kore_error`
- El endpoint siempre retorna éxito (201) si el comando se guardó en BD

## Ejemplo de Uso

### Crear un comando para un dispositivo con KORE

```bash
curl -X POST "http://localhost:8000/api/v1/commands" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "command": "AT^PRG;0848028047;10;81#001F803F",
    "media": "sms",
    "device_id": "DEV001"
  }'
```

**Respuesta exitosa (enviado vía KORE):**
```json
{
  "command_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "sent"
}
```

**Respuesta (sin KORE configurado o sin kore_sim_id):**
```json
{
  "command_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending"
}
```

## Logs

El servicio genera logs para facilitar el debugging:

```
[KORE AUTH] Autenticación exitosa. Token expira en 3600s
[COMMANDS] Enviando comando vía KORE para device_id=DEV001, kore_sim_id=HS0ad6...
[KORE SMS] Comando enviado exitosamente a SIM HS0ad6...
[COMMANDS] Comando enviado exitosamente vía KORE: command_id=550e8400-...
```

## Seguridad

- Las credenciales de KORE se almacenan en variables de entorno
- El token de autenticación tiene una duración de 1 hora (3600 segundos)
- Las comunicaciones con KORE usan HTTPS

## Referencias

- [KORE Wireless API Documentation](https://developer.korewireless.com/)
- [SuperSIM API Reference](https://supersim.api.korewireless.com/docs)

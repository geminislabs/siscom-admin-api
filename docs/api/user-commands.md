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

---

## Autenticación y permisos

- Requiere autenticación Cognito.
- Solo usuario master puede ejecutar este endpoint.

Si el usuario no es master, responde 403.

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

## Errores

| Código | Caso |
| ------ | ---- |
| 400 | ENGINE_STOP sin confirmation |
| 400 | accepted_risk distinto de true para ENGINE_STOP |
| 400 | Dispositivo sin SIM KORE configurada |
| 401 | Contraseña inválida |
| 403 | Usuario no master |
| 404 | Unidad no encontrada |
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

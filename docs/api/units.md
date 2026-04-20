# API de Unidades

## Descripción

Endpoints para gestionar unidades (vehículos, maquinaria, etc.) del cliente. Las unidades representan los activos físicos que pueden tener dispositivos GPS asignados. El acceso a las unidades se controla mediante roles: los usuarios maestros tienen acceso completo, mientras que los usuarios regulares solo pueden ver las unidades que les han sido asignadas explícitamente.

---

## Endpoints

### 1. Listar Unidades

**GET** `/api/v1/units/`

Lista las unidades visibles para el usuario autenticado según sus permisos:

- **Usuario maestro**: Ve todas las unidades del cliente
- **Usuario regular**: Solo ve las unidades asignadas en `user_units`

#### Headers

```
Authorization: Bearer <access_token>
```

#### Query Parameters (opcionales)

- `include_deleted` (boolean): Incluir unidades eliminadas. Solo para usuarios maestros. Default: `false`

#### Response 200 OK

```json
[
  {
    "id": "abc12345-e89b-12d3-a456-426614174000",
    "client_id": "def45678-e89b-12d3-a456-426614174000",
    "name": "Camión #45",
    "description": "Camión de reparto zona norte",
    "deleted_at": null
  },
  {
    "id": "xyz78901-e89b-12d3-a456-426614174000",
    "client_id": "def45678-e89b-12d3-a456-426614174000",
    "name": "Camioneta #12",
    "description": "Distribución zona sur",
    "deleted_at": null
  }
]
```

---

### 2. Crear Unidad

**POST** `/api/v1/units/`

Crea una nueva unidad en el sistema.

#### Permisos Requeridos

- Usuario maestro del cliente

#### Headers

```
Authorization: Bearer <access_token>
```

#### Request Body

El endpoint acepta payload mínimo o payload extendido para crear, en una sola llamada:

- Registro en `units`
- Registro en `unit_profile`
- Registro en `vehicle_profile` (si se envía `plate` o `vin`)
- Asignación de dispositivo (si se envía `deviceId`/`device_id`)

Se acepta **camelCase** y **snake_case** para campos equivalentes:

- `deviceId` o `device_id`
- `iconType` o `icon_type`

##### Ejemplo mínimo

```json
{
  "name": "Camión #45",
  "description": "Camión de reparto zona norte"
}
```

##### Ejemplo extendido

```json
{
  "name": "Nombre de la unidad (requerido)",
  "description": "Descripción (opcional)",
  "deviceId": "ID del dispositivo (opcional)",
  "iconType": "vehicle-car-sedan",
  "brand": "Ford",
  "model": "F-350",
  "color": "Rojo",
  "year": 2024,
  "plate": "ABC-123",
  "vin": "1FDUF3GT5GED12345"
}
```

**Campos:**

- `name` (string, requerido): Nombre de la unidad (1-200 caracteres)
- `description` (string, opcional): Descripción adicional de la unidad (máx. 500 caracteres)
- `deviceId` / `device_id` (string, opcional): ID del dispositivo a asignar (10-50 caracteres)
- `iconType` / `icon_type` (string, opcional): Tipo de icono para `unit_profile`
- `brand` (string, opcional): Marca en `unit_profile`
- `model` (string, opcional): Modelo en `unit_profile`
- `color` (string, opcional): Color en `unit_profile`
- `year` (integer, opcional): Año en `unit_profile` (1900-2100)
- `plate` (string, opcional): Placa en `vehicle_profile`
- `vin` (string, opcional): VIN en `vehicle_profile`

#### Response 201 Created

```json
{
  "id": "abc12345-e89b-12d3-a456-426614174000",
  "client_id": "def45678-e89b-12d3-a456-426614174000",
  "name": "Camión #45",
  "description": "Camión de reparto zona norte",
  "deleted_at": null
}
```

#### Errores Comunes

- **403 Forbidden**: El usuario no es maestro
- **404 Not Found**: El dispositivo enviado no existe o no pertenece a la organización
- **400 Bad Request**: El dispositivo no está en estado válido para asignación o ya está asignado

---

### 3. Obtener Detalle de Unidad

**GET** `/api/v1/units/{unit_id}`

Obtiene información detallada de una unidad específica, incluyendo contadores de dispositivos asignados.

#### Permisos Requeridos

- Usuario maestro del cliente, o
- Usuario con acceso a la unidad (registro en `user_units`)

#### Headers

```
Authorization: Bearer <access_token>
```

#### Response 200 OK

```json
{
  "id": "abc12345-e89b-12d3-a456-426614174000",
  "client_id": "def45678-e89b-12d3-a456-426614174000",
  "name": "Camión #45",
  "description": "Camión de reparto zona norte",
  "deleted_at": null,
  "active_devices_count": 2,
  "total_devices_count": 3
}
```

**Campos adicionales:**

- `active_devices_count`: Número de dispositivos actualmente asignados
- `total_devices_count`: Total de dispositivos asignados (histórico)

#### Errores Comunes

- **404 Not Found**: Unidad no encontrada o no pertenece al cliente
- **403 Forbidden**: No tienes permiso para acceder a esta unidad

---

### 4. Actualizar Unidad

**PATCH** `/api/v1/units/{unit_id}`

Actualiza los datos de una unidad existente.

#### Permisos Requeridos

- Usuario maestro del cliente, o
- Usuario con rol `editor` o `admin` en la unidad

#### Headers

```
Authorization: Bearer <access_token>
```

#### Request Body

Todos los campos son opcionales. Solo se actualizan los campos enviados.

```json
{
  "name": "Camión #45 (Renovado)",
  "description": "Camión de reparto - Zona norte y centro"
}
```

#### Response 200 OK

```json
{
  "id": "abc12345-e89b-12d3-a456-426614174000",
  "client_id": "def45678-e89b-12d3-a456-426614174000",
  "name": "Camión #45 (Renovado)",
  "description": "Camión de reparto - Zona norte y centro",
  "deleted_at": null
}
```

#### Errores Comunes

- **404 Not Found**: Unidad no encontrada
- **403 Forbidden**: Se requiere rol 'editor' o superior

---

### 5. Eliminar Unidad

**DELETE** `/api/v1/units/{unit_id}`

Elimina una unidad del sistema (soft delete - no se elimina físicamente, solo se marca como eliminada).

#### Permisos Requeridos

- Usuario maestro del cliente

#### Headers

```
Authorization: Bearer <access_token>
```

#### Validaciones

- La unidad no debe tener dispositivos activos asignados
- Solo se puede eliminar si no tiene asignaciones activas en `unit_devices`

#### Response 200 OK

```json
{
  "message": "Unidad eliminada exitosamente",
  "unit_id": "abc12345-e89b-12d3-a456-426614174000",
  "deleted_at": "2025-11-21T14:30:00Z"
}
```

#### Errores Comunes

- **403 Forbidden**: Solo los usuarios maestros pueden eliminar unidades
- **404 Not Found**: Unidad no encontrada
- **400 Bad Request**: No se puede eliminar la unidad porque tiene 2 dispositivo(s) activo(s) asignado(s)

---

## Endpoints Jerárquicos (Recursos Anidados)

### 6. Obtener Dispositivo de Unidad

**GET** `/api/v1/units/{unit_id}/device`

Devuelve el dispositivo actualmente asignado a una unidad específica.

#### Permisos Requeridos

- Usuario maestro del cliente, o
- Usuario con acceso a la unidad

#### Headers

```
Authorization: Bearer <access_token>
```

#### Response 200 OK

```json
{
  "device_id": "864537040123456",
  "brand": "Suntech",
  "model": "ST300",
  "firmware_version": "1.2.3",
  "status": "asignado",
  "active": true,
  "client_id": "def45678-e89b-12d3-a456-426614174000",
  "notes": "Dispositivo GPS principal",
  "created_at": "2025-10-01T10:00:00Z",
  "last_assignment_at": "2025-11-03T08:00:00Z"
}
```

Si no hay dispositivo asignado, retorna `null`.

---

### 7. Asignar/Reemplazar Dispositivo

**POST** `/api/v1/units/{unit_id}/device`

Asigna un dispositivo GPS a una unidad. Si la unidad ya tiene un dispositivo asignado, lo desasigna automáticamente y asigna el nuevo.

#### Permisos Requeridos

- Usuario maestro del cliente, o
- Usuario con rol `editor` o `admin` en la unidad

#### Headers

```
Authorization: Bearer <access_token>
```

#### Request Body

```json
{
  "device_id": "864537040123456"
}
```

#### Validaciones

- El dispositivo debe existir y pertenecer al cliente
- El dispositivo debe estar en estado `entregado` o `devuelto`
- El dispositivo no debe estar asignado a otra unidad activa

#### Comportamiento

1. Si la unidad tiene un dispositivo activo, lo desasigna automáticamente
2. Asigna el nuevo dispositivo
3. Actualiza el estado del dispositivo a `asignado`
4. Crea eventos en `device_events` para auditoría

#### Response 201 Created

```json
{
  "id": "xyz12345-e89b-12d3-a456-426614174000",
  "unit_id": "abc12345-e89b-12d3-a456-426614174000",
  "device_id": "864537040123456",
  "assigned_at": "2025-11-21T14:35:00Z",
  "unassigned_at": null
}
```

#### Errores Comunes

- **404 Not Found**: Dispositivo no encontrado o no pertenece a tu cliente
- **400 Bad Request**: El dispositivo debe estar en estado 'entregado' o 'devuelto'
- **400 Bad Request**: El dispositivo ya está asignado a otra unidad activa
- **403 Forbidden**: Se requiere rol 'editor' o superior

---

### 8. Listar Usuarios de Unidad

**GET** `/api/v1/units/{unit_id}/users`

Lista todos los usuarios que tienen acceso a una unidad específica.

#### Permisos Requeridos

- Usuario maestro del cliente, o
- Usuario con acceso a la unidad

#### Headers

```
Authorization: Bearer <access_token>
```

#### Response 200 OK

```json
[
  {
    "id": "xyz78901-e89b-12d3-a456-426614174000",
    "user_id": "user123-e89b-12d3-a456-426614174000",
    "unit_id": "abc12345-e89b-12d3-a456-426614174000",
    "granted_by": "master123-e89b-12d3-a456-426614174000",
    "granted_at": "2025-11-06T10:00:00Z",
    "role": "editor",
    "user_email": "operador@cliente.com",
    "user_full_name": "Juan Operador",
    "unit_name": "Camión #45",
    "granted_by_email": "maestro@cliente.com"
  }
]
```

---

### 9. Asignar Usuario a Unidad

**POST** `/api/v1/units/{unit_id}/users`

Otorga acceso a un usuario para una unidad específica con un rol determinado.

#### Permisos Requeridos

- Usuario maestro del cliente

#### Headers

```
Authorization: Bearer <access_token>
```

#### Request Body

```json
{
  "user_id": "user123-e89b-12d3-a456-426614174000",
  "role": "editor"
}
```

**Campos:**

- `user_id` (UUID, requerido): ID del usuario a asignar
- `role` (string, opcional): Rol del usuario. Default: `"viewer"`

**Roles disponibles:**

- `viewer`: Solo puede ver la unidad y sus datos
- `editor`: Puede ver y editar la unidad
- `admin`: Puede ver, editar y gestionar dispositivos

#### Validaciones

- El usuario debe pertenecer al mismo cliente
- La unidad debe pertenecer al cliente
- No se pueden asignar usuarios maestros (ya tienen acceso a todo)
- No debe existir una asignación previa

#### Response 201 Created

```json
{
  "message": "Usuario asignado exitosamente",
  "assignment_id": "xyz78901-e89b-12d3-a456-426614174000",
  "user_email": "operador@cliente.com",
  "unit_name": "Camión #45",
  "role": "editor"
}
```

#### Errores Comunes

- **403 Forbidden**: Solo los usuarios maestros pueden asignar usuarios a unidades
- **404 Not Found**: Usuario no encontrado o no pertenece a tu cliente
- **404 Not Found**: Unidad no encontrada
- **400 Bad Request**: No es necesario asignar usuarios maestros (ya tienen acceso a todas las unidades)
- **400 Bad Request**: El usuario ya tiene acceso a esta unidad con rol 'viewer'

---

### 10. Revocar Acceso de Usuario

**DELETE** `/api/v1/units/{unit_id}/users/{user_id}`

Revoca el acceso de un usuario a una unidad específica.

#### Permisos Requeridos

- Usuario maestro del cliente

#### Headers

```
Authorization: Bearer <access_token>
```

#### Response 200 OK

```json
{
  "message": "Acceso revocado exitosamente",
  "user_email": "operador@cliente.com",
  "unit_name": "Camión #45"
}
```

#### Errores Comunes

- **403 Forbidden**: Solo los usuarios maestros pueden revocar accesos a unidades
- **404 Not Found**: Unidad no encontrada
- **404 Not Found**: El usuario no tiene acceso a esta unidad

---

## Modelo de Control de Acceso

### Usuario Maestro

- Tiene acceso completo a todas las unidades del cliente
- Puede crear, editar y eliminar cualquier unidad
- Puede asignar y revocar acceso de usuarios a unidades
- No necesita estar en `user_units` para acceder

### Usuario Regular

- Solo puede ver las unidades que le fueron asignadas en `user_units`
- Sus permisos dependen del rol asignado:
  - **viewer**: Solo lectura
  - **editor**: Lectura y edición de datos básicos
  - **admin**: Lectura, edición y gestión de dispositivos

---

## Jerarquía de Roles

```
viewer < editor < admin < maestro
```

Cuando se requiere un rol específico, se acepta ese rol o cualquiera superior. Por ejemplo, si se requiere `editor`, también se acepta `admin` y maestro.

---

## Notas Importantes

### Soft Delete

- Las unidades eliminadas no se borran físicamente de la base de datos
- Se marca el campo `deleted_at` con la fecha de eliminación
- Las unidades eliminadas no aparecen en listados por defecto
- Solo usuarios maestros pueden incluir eliminadas con `include_deleted=true`

### Validaciones de Integridad

- No se puede eliminar una unidad con dispositivos activos
- No se puede asignar un dispositivo que ya está en otra unidad
- Los dispositivos deben estar en estado apropiado antes de asignarse

### Multi-tenant

- Todas las operaciones están aisladas por `client_id`
- Los usuarios solo pueden ver/modificar unidades de su cliente
- El `client_id` se extrae automáticamente del token JWT

### Auditoría

- Todas las asignaciones registran quién las realizó (`granted_by`)
- Los cambios de dispositivos crean eventos en `device_events`
- Las fechas de asignación/desasignación se registran para historial

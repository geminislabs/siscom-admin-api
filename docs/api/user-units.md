# API de Asignaciones Usuario-Unidad

## Descripción

Endpoints para gestionar los permisos de acceso de usuarios a unidades específicas. Este módulo controla qué usuarios regulares pueden ver y operar sobre qué unidades, y con qué nivel de permisos (viewer, editor, admin).

Los usuarios maestros no necesitan asignaciones explícitas ya que tienen acceso completo a todas las unidades de su cliente.

---

## Endpoints

### 1. Listar Asignaciones Usuario-Unidad

**GET** `/api/v1/user-units/`

Lista todas las asignaciones de usuario→unidad del cliente autenticado.

#### Permisos Requeridos

- Usuario maestro del cliente

#### Headers

```
Authorization: Bearer <access_token>
```

#### Query Parameters (opcionales)

- `unit_id` (UUID): Filtrar por unidad específica
- `user_id` (UUID): Filtrar por usuario específico

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
  },
  {
    "id": "abc45678-e89b-12d3-a456-426614174000",
    "user_id": "user456-e89b-12d3-a456-426614174000",
    "unit_id": "abc12345-e89b-12d3-a456-426614174000",
    "granted_by": "master123-e89b-12d3-a456-426614174000",
    "granted_at": "2025-11-10T14:30:00Z",
    "role": "viewer",
    "user_email": "supervisor@cliente.com",
    "user_full_name": "María Supervisor",
    "unit_name": "Camión #45",
    "granted_by_email": "maestro@cliente.com"
  }
]
```

#### Uso con Filtros

**Ejemplo: Ver todos los usuarios asignados a una unidad específica**

```
GET /api/v1/user-units/?unit_id=abc12345-e89b-12d3-a456-426614174000
```

**Ejemplo: Ver todas las unidades asignadas a un usuario específico**

```
GET /api/v1/user-units/?user_id=user123-e89b-12d3-a456-426614174000
```

#### Errores Comunes

- **403 Forbidden**: Solo los usuarios maestros pueden gestionar permisos de unidades

---

### 2. Crear Asignación Usuario-Unidad

**POST** `/api/v1/user-units/`

Otorga acceso a un usuario para que pueda ver y operar sobre una unidad específica.

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
  "unit_id": "abc12345-e89b-12d3-a456-426614174000",
  "role": "editor",
  "include_history": false
}
```

**Qué histórico ve el usuario:** por defecto, sólo lo ocurrido en la unidad
desde que se le concede (recorridos, alertas, posiciones). Con
`include_history: true` ve también lo anterior. Es una decisión explícita de
quien concede, porque el pasado de una unidad puede ser de otra persona.

**Campos:**

- `user_id` (UUID, requerido): ID del usuario a quien se otorga acceso
- `unit_id` (UUID, requerido): ID de la unidad
- `role` (string, opcional): Rol del usuario. Default: `"viewer"`

**Roles disponibles:**

- `viewer`: Solo lectura - puede ver la unidad y sus datos
- `editor`: Lectura y edición - puede modificar datos básicos de la unidad
- `admin`: Control completo - puede gestionar dispositivos y configuraciones

#### Validaciones

- El usuario debe pertenecer al mismo cliente
- La unidad debe pertenecer al cliente
- El usuario no debe ser maestro (los maestros ya tienen acceso a todo)
- No debe existir una asignación previa entre ese usuario y esa unidad
- El rol debe ser uno de los valores válidos

#### Response 201 Created

```json
{
  "id": "xyz78901-e89b-12d3-a456-426614174000",
  "user_id": "user123-e89b-12d3-a456-426614174000",
  "unit_id": "abc12345-e89b-12d3-a456-426614174000",
  "granted_by": "master123-e89b-12d3-a456-426614174000",
  "granted_at": "2025-11-21T14:40:00Z",
  "role": "editor"
}
```

#### Errores Comunes

- **403 Forbidden**: Solo los usuarios maestros pueden gestionar permisos de unidades
- **404 Not Found**: Usuario no encontrado o no pertenece a tu cliente
- **404 Not Found**: Unidad no encontrada o no pertenece a tu cliente
- **400 Bad Request**: No es necesario asignar permisos a usuarios maestros (ya tienen acceso a todas las unidades)
- **400 Bad Request**: El usuario ya tiene acceso a esta unidad con rol 'viewer'
- **400 Bad Request**: Rol inválido. Debe ser uno de: viewer, editor, admin

---

### 3. Eliminar Asignación Usuario-Unidad

**DELETE** `/api/v1/user-units/{assignment_id}`

Revoca el acceso de un usuario a una unidad eliminando la asignación.

La concesión retirada se archiva en `user_unit_grants_history` con su ventana
`[granted_at, revoked_at)`. Si se vuelve a conceder la unidad, el usuario ve
de nuevo lo ocurrido en esa ventana además de lo nuevo, y no lo del hueco entre
las dos. Sus data tokens vivos se revocan al confirmar.

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
  "assignment_id": "xyz78901-e89b-12d3-a456-426614174000",
  "user_email": "operador@cliente.com",
  "unit_name": "Camión #45"
}
```

#### Notas

- Esta es una eliminación física (hard delete), no un soft delete
- Una vez eliminada la asignación, el usuario pierde inmediatamente el acceso a la unidad
- Los usuarios maestros no se ven afectados por estas asignaciones

#### Errores Comunes

- **403 Forbidden**: Solo los usuarios maestros pueden gestionar permisos de unidades
- **404 Not Found**: Asignación no encontrada

---

## Modelo de Datos

### UserUnit

```
{
  "id": UUID,                    // ID único de la asignación
  "user_id": UUID,               // ID del usuario
  "unit_id": UUID,               // ID de la unidad
  "granted_by": UUID,            // ID del usuario maestro que otorgó el permiso
  "granted_at": DateTime,        // Fecha de asignación
  "role": String,                // Rol: viewer, editor, admin
  "include_history": Boolean     // Ver también lo anterior a granted_at
}
```

### Información Detallada

La respuesta incluye información enriquecida:

```
{
  // Campos base
  "id": UUID,
  "user_id": UUID,
  "unit_id": UUID,
  "granted_by": UUID,
  "granted_at": DateTime,
  "role": String,

  // Información adicional (para respuestas detalladas)
  "user_email": String,          // Email del usuario asignado
  "user_full_name": String,      // Nombre completo del usuario
  "unit_name": String,           // Nombre de la unidad
  "granted_by_email": String     // Email del maestro que otorgó el permiso
}
```

---

## Roles y Permisos

### Jerarquía de Roles

```
viewer < editor < admin < maestro
```

### Permisos por Rol

#### `viewer` - Solo Lectura

- ✅ Ver información de la unidad
- ✅ Ver dispositivos asignados a la unidad
- ✅ Ver usuarios asignados a la unidad
- ❌ Editar datos de la unidad
- ❌ Asignar/desasignar dispositivos
- ❌ Gestionar usuarios de la unidad

#### `editor` - Lectura y Edición

- ✅ Todo lo de `viewer`
- ✅ Editar datos básicos de la unidad (nombre, descripción)
- ✅ Asignar y desasignar dispositivos
- ❌ Eliminar la unidad
- ❌ Gestionar usuarios de la unidad

#### `admin` - Control Completo

- ✅ Todo lo de `editor`
- ✅ Eliminar la unidad (si no tiene dispositivos activos)
- ❌ Gestionar usuarios de la unidad (solo maestros)

#### Usuario `maestro`

- ✅ Acceso completo a todas las unidades
- ✅ No necesita asignaciones en `user_units`
- ✅ Puede gestionar asignaciones de otros usuarios
- ✅ Puede realizar cualquier operación

---

## Casos de Uso

### Caso 1: Asignar un Operador a una Unidad

Un usuario maestro quiere que un operador tenga acceso de lectura a una camioneta específica:

```bash
POST /api/v1/user-units/
{
  "user_id": "operador-uuid",
  "unit_id": "camioneta-uuid",
  "role": "viewer"
}
```

Ahora el operador puede:

- Ver los datos de la camioneta
- Ver el dispositivo GPS instalado
- Consultar el historial de ubicaciones

---

### Caso 2: Dar Permisos de Edición a un Supervisor

Un maestro quiere que un supervisor pueda gestionar dispositivos en varias unidades:

```bash
# Asignar supervisor a Unidad A
POST /api/v1/user-units/
{
  "user_id": "supervisor-uuid",
  "unit_id": "unidad-a-uuid",
  "role": "editor"
}

# Asignar supervisor a Unidad B
POST /api/v1/user-units/
{
  "user_id": "supervisor-uuid",
  "unit_id": "unidad-b-uuid",
  "role": "editor"
}
```

Ahora el supervisor puede:

- Editar información de ambas unidades
- Asignar/cambiar dispositivos GPS en ambas
- No puede eliminar las unidades

---

### Caso 3: Ver Todas las Unidades de un Usuario

Un maestro quiere saber a qué unidades tiene acceso un usuario específico:

```bash
GET /api/v1/user-units/?user_id=usuario-uuid
```

Respuesta: Lista de todas las unidades asignadas con sus roles respectivos.

---

### Caso 4: Ver Todos los Usuarios con Acceso a una Unidad

Un maestro quiere auditar quién tiene acceso a una unidad específica:

```bash
GET /api/v1/user-units/?unit_id=unidad-uuid
```

Respuesta: Lista de todos los usuarios con acceso y sus roles.

---

### Caso 5: Revocar Acceso

Un operador ya no trabaja con cierta unidad y se debe revocar su acceso:

```bash
# Primero listar para obtener el assignment_id
GET /api/v1/user-units/?user_id=operador-uuid&unit_id=unidad-uuid

# Luego eliminar la asignación
DELETE /api/v1/user-units/{assignment_id}
```

---

## Notas Importantes

### Usuarios Maestros

- Los usuarios maestros tienen acceso implícito a todas las unidades
- **No se debe** crear asignaciones para usuarios maestros
- El sistema rechazará intentos de crear asignaciones para maestros
- Esto evita confusión y mantiene la lógica de permisos clara

### Unicidad

- Un usuario no puede tener múltiples asignaciones a la misma unidad
- Si se intenta crear una asignación duplicada, el sistema retorna error
- Para cambiar el rol, primero se debe eliminar la asignación existente y crear una nueva

### Multi-tenant

- Todas las operaciones están aisladas por `client_id`
- Un usuario solo puede ser asignado a unidades de su mismo cliente
- Las consultas solo retornan asignaciones del cliente autenticado

### Auditoría

- Cada asignación registra quién la otorgó (`granted_by`)
- Se registra la fecha exacta de asignación (`granted_at`)
- No hay historial de cambios de roles (se debe eliminar y recrear)

### Performance

- Los listados están optimizados con índices en la base de datos
- Los filtros por `user_id` y `unit_id` son muy eficientes
- Las respuestas incluyen información enriquecida sin necesidad de múltiples queries

---

## Alternativas: Endpoints Jerárquicos

También es posible gestionar asignaciones usando los endpoints jerárquicos de `/api/v1/units/`:

- `GET /api/v1/units/{unit_id}/users` - Ver usuarios de una unidad
- `POST /api/v1/units/{unit_id}/users` - Asignar usuario a una unidad
- `DELETE /api/v1/units/{unit_id}/users/{user_id}` - Revocar acceso

Estos endpoints son equivalentes pero organizados jerárquicamente. La elección depende del caso de uso:

- **Usar `/user-units/`** cuando se gestiona desde la perspectiva de permisos globales
- **Usar `/units/{id}/users`** cuando se gestiona desde la perspectiva de una unidad específica

---

## Publicación de Eventos en Kafka

Tras el `COMMIT` de `POST` o `DELETE` (tanto `/api/v1/user-units` como `/api/v1/units/{unit_id}/users`), se publica un evento al tópico `KAFKA_USER_UNITS_UPDATES_TOPIC` (default `user-units-updates`). Key: `user_id`.

Si Kafka falla, el HTTP **no** falla: se loguea `Fallo publicando evento de control`.

```json
{
  "event_id": "uuid",
  "event_type": "UPSERT",
  "entity": "user_unit",
  "timestamp": "2026-09-03T17:22:11Z",
  "organization_id": "uuid",
  "data": {
    "user_id": "uuid",
    "unit_id": "uuid",
    "role": "viewer"
  }
}
```

`DELETE` usa `"event_type": "DELETE"`. Los masters **no** generan filas ni eventos: el distributor los resuelve por `users.is_master`.

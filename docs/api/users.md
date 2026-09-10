# API de Usuarios

## Descripción

Endpoints para gestionar usuarios dentro de una organización. Incluye funcionalidad de invitaciones, gestión de roles y permisos organizacionales.

> **Referencia**: Ver [Modelo Organizacional](../guides/organizational-model.md) para entender el sistema completo de roles y permisos.

---

## Sistema de Roles Organizacionales

### Jerarquía de Roles

```
┌──────────┐  Permisos totales sobre la organización
│  OWNER   │  Único por organización, puede transferir ownership
└────┬─────┘
     │
┌────┴─────┐  Gestión completa (usuarios, configuración)
│  ADMIN   │  Puede invitar/eliminar usuarios (excepto owner)
└────┬─────┘
     │
┌────┴─────┐  Gestión de pagos y facturación
│ BILLING  │  Ve información de suscripciones, puede realizar pagos
└────┬─────┘
     │
┌────┴─────┐  Acceso operativo
│  MEMBER  │  Ve dispositivos y unidades asignadas
└──────────┘
```

### Matriz de Permisos por Rol

| Acción | Owner | Admin | Billing | Member |
|--------|:-----:|:-----:|:-------:|:------:|
| Ver organización | ✅ | ✅ | ✅ | ✅ |
| Editar organización | ✅ | ✅ | ❌ | ❌ |
| Ver usuarios | ✅ | ✅ | ❌ | ❌ |
| Invitar usuarios | ✅ | ✅ | ❌ | ❌ |
| Eliminar usuarios | ✅ | ✅* | ❌ | ❌ |
| Cambiar roles | ✅ | ✅** | ❌ | ❌ |
| Ver suscripciones | ✅ | ✅ | ✅ | ❌ |
| Gestionar suscripciones | ✅ | ❌ | ✅ | ❌ |
| Ver pagos | ✅ | ❌ | ✅ | ❌ |
| Realizar pagos | ✅ | ❌ | ✅ | ❌ |
| Ver todos los dispositivos | ✅ | ✅ | ❌ | ❌ |
| Ver dispositivos asignados | ✅ | ✅ | ❌ | ✅ |
| Gestionar dispositivos | ✅ | ✅ | ❌ | ❌ |
| Transferir ownership | ✅ | ❌ | ❌ | ❌ |

*Admin no puede eliminar al Owner  
**Admin no puede asignar rol de Owner

### Mapeo con `is_master` (Legacy)

| `is_master` | Rol Equivalente | Contexto |
|-------------|-----------------|----------|
| `true` (primer usuario) | `owner` | Usuario que creó la organización |
| `true` (invitado como master) | `admin` | Usuario con permisos de gestión |
| `false` | `member` | Usuario operativo básico |

> **Nota de Migración**: El campo `is_master` se mantiene por compatibilidad pero debe complementarse con roles explícitos en `organization_users`.

---

## Endpoints

### 1. Listar Usuarios

**GET** `/api/v1/users/`

Lista todos los usuarios de la organización del usuario autenticado.

#### Headers

```
Authorization: Bearer <access_token>
```

#### Permisos Requeridos

- Rol: `owner`, `admin`
- `is_master: true` (legacy)

#### Response 200 OK

> **Sobre `cognito_sub` en las respuestas:** es el **sujeto del token** (el claim
> `sub`), no el handle con el que el usuario se autentica. Ese handle vive en
> `users.external_id` y **no se expone por la API**: es interno del proveedor de
> identidad y opaco por contrato. Ver
> [Identidad y marca](../architecture/identidad-y-marca.md).

```json
[
  {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "client_id": "456e4567-e89b-12d3-a456-426614174000",
    "email": "owner@ejemplo.com",
    "full_name": "Juan Pérez",
    "role": "owner",
    "is_master": true,
    "email_verified": true,
    "cognito_sub": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "last_login_at": "2024-01-20T10:00:00Z",
    "created_at": "2024-01-15T10:30:00Z"
  },
  {
    "id": "234e4567-e89b-12d3-a456-426614174001",
    "client_id": "456e4567-e89b-12d3-a456-426614174000",
    "email": "admin@ejemplo.com",
    "full_name": "María García",
    "role": "admin",
    "is_master": true,
    "email_verified": true,
    "cognito_sub": "b2c3d4e5-f6g7-8901-bcde-f23456789012",
    "last_login_at": "2024-01-19T15:30:00Z",
    "created_at": "2024-01-18T09:00:00Z"
  },
  {
    "id": "345e4567-e89b-12d3-a456-426614174002",
    "client_id": "456e4567-e89b-12d3-a456-426614174000",
    "email": "contador@ejemplo.com",
    "full_name": "Carlos López",
    "role": "billing",
    "is_master": false,
    "email_verified": true,
    "cognito_sub": "c3d4e5f6-g7h8-9012-cdef-345678901234",
    "created_at": "2024-02-01T09:00:00Z"
  }
]
```

---

### 2. Obtener Usuario Actual

**GET** `/api/v1/users/me`

Obtiene la información del usuario actualmente autenticado, incluyendo su rol en la organización.

#### Headers

```
Authorization: Bearer <access_token>
```

#### Response 200 OK

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "client_id": "456e4567-e89b-12d3-a456-426614174000",
  "email": "usuario@ejemplo.com",
  "full_name": "Juan Pérez",
  "role": "owner",
  "is_master": true,
  "email_verified": true,
  "cognito_sub": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "last_login_at": "2024-01-20T10:00:00Z",
  "created_at": "2024-01-15T10:30:00Z",
  "permissions": {
    "can_invite_users": true,
    "can_manage_billing": true,
    "can_view_all_devices": true,
    "can_manage_organization": true
  }
}
```

---

### 3. Invitar Usuario

**POST** `/api/v1/users/invite`

Permite a un usuario con permisos de gestión enviar una invitación a un nuevo usuario.

#### Headers

```
Authorization: Bearer <access_token>
```

#### Permisos Requeridos

- Rol: `owner`, `admin`
- `is_master: true` (legacy)

#### Request Body

```json
{
  "email": "invitado@ejemplo.com",
  "full_name": "María García",
  "role": "member"
}
```

#### Roles Asignables

| Rol que Invita | Puede Asignar |
|----------------|---------------|
| `owner` | `admin`, `billing`, `member` |
| `admin` | `admin`, `billing`, `member` |

> **Nota**: Nadie puede asignar el rol `owner` por invitación. El ownership solo se transfiere.

#### Validaciones

- El usuario autenticado debe tener permisos de invitación
- El email no debe estar ya registrado en el sistema
- No debe existir una invitación pendiente para ese email
- El rol asignado debe ser válido según permisos del invitador

#### Response 201 Created

```json
{
  "message": "Invitación enviada exitosamente.",
  "email": "invitado@ejemplo.com",
  "role": "member",
  "expires_at": "2025-01-22T10:30:00Z"
}
```

#### Errores Comunes

| Código | Detalle |
|--------|---------|
| 403 | `"No tiene permisos para invitar usuarios"` |
| 400 | `"Ya existe un usuario con ese email"` |
| 400 | `"Ya existe una invitación pendiente para ese email"` |
| 400 | `"Rol inválido"` |

---

### 4. Aceptar Invitación

**POST** `/api/v1/users/accept-invitation`

Permite a un usuario invitado aceptar la invitación y crear su cuenta.

#### Request Body

```json
{
  "token": "abc123def456...",
  "password": "MiPassword123!"
}
```

#### Validaciones

- El token debe ser válido y no estar expirado
- El token no debe haber sido usado previamente
- La contraseña debe cumplir los requisitos de seguridad

#### Response 201 Created

```json
{
  "message": "Invitación aceptada exitosamente. Ya puedes iniciar sesión.",
  "email": "invitado@ejemplo.com",
  "user_id": "789e4567-e89b-12d3-a456-426614174000",
  "role": "member"
}
```

#### Proceso Interno

```
1. Validar token de invitación
   ↓
2. Crear usuario en AWS Cognito con estado CONFIRMED
   ↓
3. Crear registro en tabla users
   ↓
4. Crear registro en organization_users con rol asignado
   ↓
5. Marcar token como usado
   ↓
6. (Opcional) Enviar email de bienvenida
```

---

### 5. Reenviar Invitación

**POST** `/api/v1/users/resend-invitation`

Reenvía una invitación a un email que tiene una invitación pendiente.

#### Headers

```
Authorization: Bearer <access_token>
```

#### Permisos Requeridos

- Rol: `owner`, `admin`
- `is_master: true` (legacy)

#### Request Body

```json
{
  "email": "invitado@ejemplo.com"
}
```

#### Validaciones

- El usuario autenticado debe tener permisos de invitación
- Debe existir una invitación pendiente para ese email
- La invitación puede estar expirada (se renovará)

#### Response 200 OK

```json
{
  "message": "Invitación reenviada exitosamente.",
  "email": "invitado@ejemplo.com",
  "new_expires_at": "2025-01-22T15:45:00Z"
}
```

---

### 6. Cambiar Rol de Usuario (Esperado)

**PATCH** `/api/v1/users/{user_id}/role`

> **Estado**: Endpoint esperado para implementación

Permite cambiar el rol de un usuario existente.

#### Request Body

```json
{
  "new_role": "admin"
}
```

#### Permisos para Cambio de Rol

| Rol Actual | Quien Puede Cambiar | Roles Asignables |
|------------|---------------------|------------------|
| `member` | `owner`, `admin` | `admin`, `billing`, `member` |
| `billing` | `owner`, `admin` | `admin`, `billing`, `member` |
| `admin` | `owner` | `billing`, `member` |
| `owner` | (solo transferencia) | N/A |

#### Response Esperado

```json
{
  "message": "Rol actualizado exitosamente",
  "user_id": "user-uuid",
  "previous_role": "member",
  "new_role": "admin"
}
```

---

### 7. Transferir Ownership (Esperado)

**POST** `/api/v1/users/{user_id}/transfer-ownership`

> **Estado**: Endpoint esperado para implementación

Permite al owner actual transferir el ownership a otro usuario.

#### Permisos Requeridos

- Solo el `owner` actual puede transferir
- El usuario destino debe ser parte de la organización

#### Request Body

```json
{
  "confirm_email": "owner_actual@ejemplo.com"
}
```

#### Response Esperado

```json
{
  "message": "Ownership transferido exitosamente",
  "previous_owner": {
    "id": "user-uuid-1",
    "email": "owner_anterior@ejemplo.com",
    "new_role": "admin"
  },
  "new_owner": {
    "id": "user-uuid-2",
    "email": "nuevo_owner@ejemplo.com",
    "role": "owner"
  }
}
```

---

### 8. Eliminar Usuario (Esperado)

**DELETE** `/api/v1/users/{user_id}`

> **Estado**: Endpoint esperado para implementación

Elimina un usuario de la organización.

#### Permisos Requeridos

- Rol: `owner`, `admin`
- No se puede eliminar al owner
- Admin no puede eliminar a otro admin o al owner

#### Response Esperado

```json
{
  "message": "Usuario eliminado exitosamente",
  "user_id": "user-uuid",
  "email": "usuario_eliminado@ejemplo.com"
}
```

---

## Flujos de Usuario

### Flujo de Invitación Completo

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUJO DE INVITACIÓN                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. ENVÍO DE INVITACIÓN (Owner/Admin)                          │
│     POST /api/v1/users/invite                                   │
│     {"email": "...", "full_name": "...", "role": "member"}     │
│                          ↓                                      │
│     Token generado + Email enviado                              │
│                                                                 │
│  2. ACEPTACIÓN (Usuario Invitado)                              │
│     Clic en link del email                                      │
│     POST /api/v1/users/accept-invitation                        │
│     {"token": "...", "password": "..."}                        │
│                          ↓                                      │
│     Usuario creado en Cognito + BD                              │
│     Rol asignado en organization_users                          │
│                                                                 │
│  3. LOGIN                                                       │
│     POST /api/v1/auth/login                                     │
│     Usuario puede acceder según su rol                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Flujo de Invitación Expirada

```
Usuario Owner/Admin → POST /api/v1/users/resend-invitation
                    ↓
              Token renovado (7 días más)
                    ↓
              Nuevo email enviado
                    ↓
              Usuario puede aceptar con nuevo token
```

---

## Roles y Acceso a Datos

### Visibilidad de Datos por Rol

| Datos | Owner | Admin | Billing | Member |
|-------|:-----:|:-----:|:-------:|:------:|
| Todos los dispositivos | ✅ | ✅ | ❌ | ❌ |
| Dispositivos asignados | ✅ | ✅ | ❌ | ✅ |
| Todas las unidades | ✅ | ✅ | ❌ | ❌ |
| Unidades asignadas | ✅ | ✅ | ❌ | ✅ |
| Lista de usuarios | ✅ | ✅ | ❌ | ❌ |
| Suscripciones | ✅ | ✅ | ✅ | ❌ |
| Historial de pagos | ✅ | ❌ | ✅ | ❌ |
| Capabilities | ✅ | ✅ | ❌ | ❌ |

### Asignación de Usuarios a Unidades

Los usuarios con rol `member` solo ven las unidades que les han sido asignadas explícitamente:

```
Organización "Transportes XYZ"
├── Unidad "Camioneta 01" → Asignada a María (member) ✓
├── Unidad "Camioneta 02" → Asignada a Carlos (member) ✓
├── Unidad "Camioneta 03" → Sin asignar
└── Unidad "Camioneta 04" → Asignada a María (member) ✓

María ve: Camioneta 01, Camioneta 04
Carlos ve: Camioneta 02
Owner/Admin ven: Todas
```

---

## Notas Importantes

### Expiración de Tokens de Invitación

- Las invitaciones expiran en **7 días** por defecto
- Los tokens usados no pueden reutilizarse
- Una invitación puede reenviarse múltiples veces

### Multi-tenant

- Cada usuario pertenece a una única organización
- Los usuarios solo ven datos de su propia organización
- El `organization_id` (client_id) se extrae automáticamente del token JWT

### Seguridad

- Solo usuarios con permisos de gestión (owner, admin) pueden invitar
- Las invitaciones no pueden modificar el `organization_id`
- Los tokens son UUID únicos y no predecibles
- El rol se valida en cada operación sensible

### Auditoría de Roles

Se recomienda registrar:
- Cambios de rol
- Invitaciones enviadas
- Usuarios eliminados
- Transferencias de ownership

---

## Ejemplos de Uso

### Invitar un Contador (Rol Billing)

```bash
# Como owner o admin
curl -X POST http://localhost:8000/api/v1/users/invite \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "contador@empresa.com",
    "full_name": "Ana Martínez",
    "role": "billing"
  }'
```

### Invitar un Operador (Rol Member)

```bash
curl -X POST http://localhost:8000/api/v1/users/invite \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "operador@empresa.com",
    "full_name": "Pedro Sánchez",
    "role": "member"
  }'
```

### Aceptar Invitación

```bash
curl -X POST http://localhost:8000/api/v1/users/accept-invitation \
  -H "Content-Type: application/json" \
  -d '{
    "token": "abc123def456...",
    "password": "MiPassword123!"
  }'
```

---

**Última actualización**: Diciembre 2025  
**Referencia**: [Modelo Organizacional](../guides/organizational-model.md)

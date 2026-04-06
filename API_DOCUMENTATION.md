# 📘 SISCOM Admin API - Documentación Completa

## 🎯 Descripción General

**SISCOM Admin API** es una plataforma **SaaS B2B multi-tenant** para la gestión integral de sistemas de rastreo GPS/IoT. Permite a múltiples organizaciones administrar dispositivos de rastreo, vehículos/unidades, usuarios con roles específicos, planes de servicio con capabilities, y facturación de manera completamente aislada.

> **Referencia de Arquitectura**: Ver [Modelo Organizacional](docs/guides/organizational-model.md) para entender la semántica completa de negocio.

### Conceptos Fundamentales

| Concepto | Descripción |
|----------|-------------|
| **Organización** | Entidad de negocio (raíz operativa) |
| **Suscripciones** | Contratos de servicio - una organización puede tener **múltiples** |
| **Capabilities** | Límites y features que gobiernan el acceso |
| **Roles** | Permisos de usuarios: owner, admin, billing, member |

### Características Principales

- 🏢 **Multi-tenant**: Cada organización tiene sus datos completamente aislados
- 🔐 **Autenticación Dual**: AWS Cognito (usuarios) + PASETO (servicios internos)
- 📱 **Gestión de Dispositivos GPS**: Inventario y seguimiento completo de dispositivos
- 🚗 **Gestión de Unidades/Vehículos**: Organización de flotas con permisos granulares
- 👥 **Sistema de Roles**: owner, admin, billing, member con permisos específicos
- 💳 **Suscripciones Múltiples**: Una organización puede tener varias suscripciones
- 🎛️ **Capabilities**: Sistema de límites y features configurable por plan y organización
- 📧 **Notificaciones por Email**: Sistema integrado con AWS SES
- 📊 **Auditoría**: Registro completo de eventos en dispositivos

---

## 🏗️ Arquitectura

### Stack Tecnológico

- **Framework**: FastAPI 0.109.0
- **Base de Datos**: PostgreSQL 16
- **ORM**: SQLAlchemy 2.x / SQLModel
- **Autenticación**: AWS Cognito
- **Emails**: AWS SES con templates Jinja2
- **Deployment**: Docker + GitHub Actions CI/CD
- **Documentación Interactiva**: Swagger UI / ReDoc

### URL Base

```
Desarrollo: http://localhost:8100
Producción: https://api.tudominio.com
```

### Versionado

Todas las rutas de la API están bajo el prefijo `/api/v1`

```
http://localhost:8100/api/v1/...
```

---

## 🔐 Autenticación

La API utiliza **AWS Cognito** con tokens JWT Bearer.

### Obtener Token de Acceso

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "usuario@ejemplo.com",
  "password": "tu_password"
}
```

**Respuesta:**

```json
{
  "user": {
    "id": "uuid",
    "email": "usuario@ejemplo.com",
    "full_name": "Usuario Ejemplo",
    "is_master": true,
    "email_verified": true
  },
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "id_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

### Usar el Token

Incluye el `access_token` en el header de todas las peticiones autenticadas:

```http
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## 📚 Endpoints por Categoría

### 📋 Índice de Endpoints

1. [**Autenticación** (`/auth`)](#1-autenticación-auth) - Login, logout, recuperación de contraseña
2. [**Cuentas** (`/accounts`)](#2-cuentas-accounts) - Registro (onboarding) y gestión de cuentas
3. [**Usuarios** (`/users`)](#3-usuarios-users) - Invitaciones y gestión de usuarios
4. [**Suscripciones** (`/subscriptions`)](#4-suscripciones-subscriptions) - Gestión de suscripciones múltiples
5. [**Capabilities** (`/capabilities`)](#5-capabilities-capabilities) - Límites y features de la organización
6. [**Dispositivos** (`/devices`)](#6-dispositivos-devices) - Inventario y gestión de GPS
7. [**Eventos de Dispositivos** (`/device-events`)](#7-eventos-de-dispositivos-device-events) - Historial de eventos
8. [**Unidades/Vehículos** (`/units`)](#8-unidades-units) - Gestión de flotas
9. [**Asignación Unidad-Dispositivo** (`/unit-devices`)](#9-asignación-unidad-dispositivo-unit-devices) - Instalaciones
10. [**Asignación Usuario-Unidad** (`/user-units`)](#10-asignación-usuario-unidad-user-units) - Permisos por unidad
11. [**Servicios** (`/services`)](#11-servicios-services) - Activación de servicios (legacy)
12. [**Planes** (`/plans`)](#12-planes-plans) - Catálogo de planes disponibles
13. [**Órdenes** (`/orders`)](#13-órdenes-orders) - Pedidos de hardware
14. [**Pagos** (`/payments`)](#14-pagos-payments) - Gestión de pagos
15. [**Alertas y Reglas** (`/alerts`, `/alert_rules`)](#15-alertas-y-reglas-alerts-alert_rules) - Consulta de alertas y administración de reglas

---

## 1. Autenticación (`/auth`)

### 🔓 Endpoints Públicos (No requieren autenticación)

#### `POST /api/v1/auth/login`

**Iniciar sesión**

Autentica a un usuario y retorna tokens de acceso.

**Request:**

```json
{
  "email": "usuario@ejemplo.com",
  "password": "Password123!"
}
```

**Response:** `200 OK`

```json
{
  "user": { ... },
  "access_token": "...",
  "id_token": "...",
  "refresh_token": "...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

---

#### `POST /api/v1/auth/forgot-password`

**Solicitar restablecimiento de contraseña**

Genera un token y envía un email con el enlace de recuperación.

**Request:**

```json
{
  "email": "usuario@ejemplo.com"
}
```

**Response:** `200 OK`

```json
{
  "message": "Se ha enviado un código de verificación al correo registrado."
}
```

**Email enviado:** Link a `{FRONTEND_URL}/reset-password?token={token}`

---

#### `POST /api/v1/auth/reset-password`

**Restablecer contraseña con token**

Usa el token recibido por email para establecer una nueva contraseña.

**Request:**

```json
{
  "token": "uuid-token-from-email",
  "new_password": "NuevaPassword123!"
}
```

**Response:** `200 OK`

```json
{
  "message": "Contraseña restablecida exitosamente. Ahora puede iniciar sesión con su nueva contraseña."
}
```

---

#### `POST /api/v1/auth/resend-verification`

**Reenviar email de verificación**

Reenvía el correo de verificación a usuarios no verificados.

**Request:**

```json
{
  "email": "usuario@ejemplo.com"
}
```

**Response:** `200 OK`

```json
{
  "message": "Si la cuenta existe, se ha reenviado el correo de verificación."
}
```

---

#### `POST /api/v1/auth/confirm-email`

**Confirmar email con token**

Verifica el email del usuario usando el token enviado por correo.

**Request:**

```json
{
  "token": "uuid-token-from-email"
}
```

**Response:** `200 OK`

```json
{
  "message": "Email verificado exitosamente. Ahora puede iniciar sesión."
}
```

---

### 🔒 Endpoints Autenticados

#### `POST /api/v1/auth/logout`

**Cerrar sesión**

Invalida todos los tokens del usuario.

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "message": "Sesión cerrada exitosamente."
}
```

---

#### `PATCH /api/v1/auth/password`

**Cambiar contraseña (usuario autenticado)**

Permite al usuario cambiar su contraseña proporcionando la actual.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "old_password": "PasswordActual123!",
  "new_password": "NuevaPassword123!"
}
```

**Response:** `200 OK`

```json
{
  "message": "Contraseña actualizada exitosamente."
}
```

---

## 2. Cuentas (`/accounts`)

> **Nota Conceptual**: El endpoint `/accounts` maneja la gestión de cuentas. El registro se realiza en `POST /api/v1/auth/register`. Ver [docs/api/accounts.md](docs/api/accounts.md) para detalles completos.

**Request (campos obligatorios):**

```json
{
  "account_name": "Mi Empresa S.A.",
  "email": "admin@miempresa.com",
  "password": "Password123!"
}
```

**Request (con campos opcionales):**

```json
{
  "account_name": "Mi Empresa S.A.",
  "name": "Juan Pérez López",
  "organization_name": "Flota Norte",
  "email": "admin@miempresa.com",
  "password": "Password123!",
  "billing_email": "facturacion@miempresa.com",
  "country": "MX",
  "timezone": "America/Mexico_City"
}
```

| Campo | Obligatorio | Descripción |
|-------|-------------|-------------|
| `account_name` | ✅ | Nombre de la cuenta comercial |
| `email` | ✅ | Email del usuario master (único global) |
| `password` | ✅ | Contraseña (min 8 caracteres) |
| `name` | ❌ | Nombre del usuario (default: account_name) |
| `organization_name` | ❌ | Nombre de la organización (default: "ORG " + account_name) |
| `billing_email` | ❌ | Email de facturación (default: email) |
| `country` | ❌ | Código ISO país |
| `timezone` | ❌ | Zona horaria IANA |

**Response:** `201 Created`

```json
{
  "account_id": "uuid",
  "organization_id": "uuid",
  "user_id": "uuid"
}
```

**Email enviado:** Link a `{FRONTEND_URL}/verify-email?token={token}`

**Nota:** Se envía email de verificación. El usuario debe verificar antes de poder iniciar sesión.

---

### 🔒 Autenticados

#### `GET /api/v1/accounts/organization`

**Obtener información de la organización autenticada**

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "account_id": "uuid",
  "name": "Mi Empresa S.A.",
  "status": "ACTIVE",
  "billing_email": "facturacion@miempresa.com",
  "country": "MX",
  "timezone": "America/Mexico_City",
  "created_at": "2024-11-08T10:00:00Z",
  "updated_at": "2024-11-08T10:05:00Z"
}
```

> **Nota**: Ver [docs/api/accounts.md](docs/api/accounts.md) para la documentación completa de todos los endpoints de accounts.

---

## 3. Usuarios (`/users`)

> **Sistema de Roles**: Los usuarios tienen roles específicos dentro de la organización: `owner`, `admin`, `billing`, `member`. Ver [docs/api/users.md](docs/api/users.md) para detalles.

### 🔒 Todos requieren autenticación

#### `GET /api/v1/users/`

**Listar todos los usuarios de la organización**

**Headers:** `Authorization: Bearer {access_token}`
**Permisos:** `owner`, `admin`

**Response:** `200 OK`

```json
[
  {
    "id": "uuid",
    "email": "admin@miempresa.com",
    "full_name": "Administrador Principal",
    "role": "owner",
    "is_master": true,
    "email_verified": true,
    "last_login_at": "2024-11-08T10:00:00Z",
    "created_at": "2024-11-08T09:00:00Z"
  },
  {
    "id": "uuid",
    "email": "contador@miempresa.com",
    "full_name": "Usuario Facturación",
    "role": "billing",
    "is_master": false,
    "email_verified": true,
    "last_login_at": "2024-11-08T11:00:00Z",
    "created_at": "2024-11-08T09:30:00Z"
  },
  {
    "id": "uuid",
    "email": "operador@miempresa.com",
    "full_name": "Usuario Operador",
    "role": "member",
    "is_master": false,
    "email_verified": true,
    "created_at": "2024-11-08T10:00:00Z"
  }
]
```

---

#### `GET /api/v1/users/me`

**Obtener información del usuario actual**

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "email": "admin@miempresa.com",
  "full_name": "Administrador Principal",
  "is_master": true,
  "email_verified": true,
  "client_id": "uuid",
  "last_login_at": "2024-11-08T10:00:00Z",
  "created_at": "2024-11-08T09:00:00Z"
}
```

---

#### `POST /api/v1/users/invite`

**Invitar nuevo usuario** (Solo owner/admin)

Envía una invitación por email para que un nuevo usuario se registre con un rol específico.

**Headers:** `Authorization: Bearer {access_token}`
**Permisos:** `owner`, `admin`

**Request:**

```json
{
  "email": "nuevousuario@miempresa.com",
  "full_name": "Nuevo Usuario",
  "role": "member"
}
```

**Roles disponibles para asignar:**
- `admin` - Gestión de usuarios y configuración
- `billing` - Gestión de pagos y facturación
- `member` - Acceso operativo según asignaciones

> **Nota**: El rol `owner` no se puede asignar por invitación, solo por transferencia.

**Response:** `201 Created`

```json
{
  "detail": "Invitación enviada a nuevousuario@miempresa.com",
  "role": "member",
  "expires_at": "2024-11-11T10:00:00Z"
}
```

**Email enviado:** Link a `{FRONTEND_URL}/accept-invitation?token={token}`

**Errores:**

- `403 Forbidden`: Si el usuario no tiene permisos de invitación
- `400 Bad Request`: Si el email ya está registrado o tiene invitación pendiente

---

#### `POST /api/v1/users/accept-invitation`

**Aceptar invitación** (Público)

El usuario invitado usa el token para crear su cuenta.

**Request:**

```json
{
  "token": "uuid-token-from-email",
  "password": "Password123!"
}
```

**Response:** `201 Created`

```json
{
  "detail": "Usuario creado exitosamente.",
  "user": {
    "id": "uuid",
    "email": "nuevousuario@miempresa.com",
    "full_name": "Nuevo Usuario",
    "is_master": false,
    "email_verified": true
  }
}
```

---

#### `POST /api/v1/users/resend-invitation`

**Reenviar invitación** (Solo usuarios maestros)

Reenvía una invitación a un email que no ha aceptado.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "email": "nuevousuario@miempresa.com"
}
```

**Response:** `200 OK`

```json
{
  "message": "Invitación reenviada a nuevousuario@miempresa.com",
  "expires_at": "2024-11-11T10:00:00Z"
}
```

---

## 4. Suscripciones (`/subscriptions`)

Gestión de suscripciones de la organización. Una organización puede tener **múltiples** suscripciones.

> **Concepto Clave**: Las suscripciones activas se CALCULAN dinámicamente, no se almacenan como un campo fijo.

### 🔒 Todos requieren autenticación

#### `GET /api/v1/subscriptions/`

**Listar todas las suscripciones**

Lista las suscripciones de la organización, incluyendo activas e históricas.

**Headers:** `Authorization: Bearer {access_token}`

**Query Parameters:**

- `include_history` (bool, default=true): Incluir suscripciones canceladas/expiradas
- `limit` (int, default=20): Límite de resultados

**Response:** `200 OK`

```json
{
  "subscriptions": [
    {
      "id": "uuid",
      "client_id": "uuid",
      "plan_id": "uuid",
      "plan_name": "Plan Profesional",
      "plan_code": "pro",
      "status": "ACTIVE",
      "billing_cycle": "MONTHLY",
      "started_at": "2024-01-01T00:00:00Z",
      "expires_at": "2025-01-01T00:00:00Z",
      "auto_renew": true,
      "days_remaining": 180,
      "is_active": true
    }
  ],
  "active_count": 1,
  "total_count": 3
}
```

---

#### `GET /api/v1/subscriptions/active`

**Listar suscripciones activas**

Lista solo las suscripciones activas (status ACTIVE o TRIAL y no expiradas).

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
[
  {
    "id": "uuid",
    "plan_name": "Plan Profesional",
    "status": "ACTIVE",
    "expires_at": "2025-01-01T00:00:00Z",
    "days_remaining": 180,
    "is_active": true
  }
]
```

---

#### `GET /api/v1/subscriptions/{subscription_id}`

**Obtener detalles de una suscripción**

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "client_id": "uuid",
  "plan_id": "uuid",
  "plan_name": "Plan Profesional",
  "status": "ACTIVE",
  "billing_cycle": "MONTHLY",
  "started_at": "2024-01-01T00:00:00Z",
  "expires_at": "2025-01-01T00:00:00Z",
  "current_period_start": "2024-06-01T00:00:00Z",
  "current_period_end": "2024-07-01T00:00:00Z",
  "auto_renew": true,
  "external_id": "sub_stripe_123",
  "days_remaining": 180,
  "is_active": true
}
```

---

#### `POST /api/v1/subscriptions/{subscription_id}/cancel`

**Cancelar suscripción**

**Headers:** `Authorization: Bearer {access_token}`
**Permisos:** `owner`, `billing`

**Request:**

```json
{
  "reason": "Ya no necesito el servicio",
  "cancel_immediately": false
}
```

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "status": "CANCELLED",
  "cancelled_at": "2024-06-15T10:00:00Z",
  "auto_renew": false
}
```

---

#### `PATCH /api/v1/subscriptions/{subscription_id}/auto-renew`

**Activar/desactivar renovación automática**

**Headers:** `Authorization: Bearer {access_token}`
**Permisos:** `owner`, `billing`

**Query Parameters:**

- `auto_renew` (bool): Nuevo valor

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "auto_renew": false
}
```

---

## 5. Capabilities (`/capabilities`)

Sistema de límites y features de la organización. Las capabilities determinan qué puede hacer una organización.

> **Regla de Resolución**: `organization_override ?? plan_capability ?? default`

### 🔒 Todos requieren autenticación

#### `GET /api/v1/capabilities/`

**Obtener resumen de capabilities**

Retorna todas las capabilities efectivas de la organización, agrupadas en límites y features.

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "limits": {
    "max_devices": 50,
    "max_geofences": 100,
    "max_users": 10,
    "history_days": 90
  },
  "features": {
    "ai_features": true,
    "analytics_tools": true,
    "api_access": true,
    "real_time_tracking": true
  }
}
```

---

#### `GET /api/v1/capabilities/{capability_code}`

**Obtener una capability específica**

Retorna el valor y fuente de una capability específica.

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "code": "max_devices",
  "value": 100,
  "source": "organization",
  "plan_id": null,
  "expires_at": "2024-12-31T23:59:59Z"
}
```

**Valores de `source`:**
- `organization`: Override específico de la organización
- `plan`: Valor del plan activo
- `default`: Valor por defecto del sistema

---

#### `POST /api/v1/capabilities/validate-limit`

**Validar si se puede agregar un elemento**

Verifica si se puede agregar un elemento más sin exceder el límite.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "capability_code": "max_devices",
  "current_count": 8
}
```

**Response:** `200 OK`

```json
{
  "can_add": true,
  "current_count": 8,
  "limit": 10,
  "remaining": 2
}
```

---

#### `GET /api/v1/capabilities/check/{capability_code}`

**Verificar si una feature está habilitada**

Verifica rápidamente si una capability booleana está habilitada.

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "capability": "ai_features",
  "enabled": true
}
```

---

## 6. Dispositivos (`/devices`)

Gestión del inventario de dispositivos GPS.

### 🔒 Todos requieren autenticación

#### `POST /api/v1/devices/`

**Registrar nuevo dispositivo**

Agrega un dispositivo al inventario con estado "nuevo".

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "device_id": "IMEI123456789",
  "brand": "Teltonika",
  "model": "FMB120",
  "firmware_version": "03.28.07",
  "notes": "Dispositivo para instalación en vehículo comercial"
}
```

**Response:** `201 Created`

```json
{
  "device_id": "IMEI123456789",
  "brand": "Teltonika",
  "model": "FMB120",
  "firmware_version": "03.28.07",
  "status": "nuevo",
  "active": false,
  "client_id": null,
  "notes": "Dispositivo para instalación en vehículo comercial",
  "created_at": "2024-11-08T10:00:00Z"
}
```

**Estados del dispositivo:**

- `nuevo`: Recién registrado, sin asignar
- `asignado`: Asignado a un cliente
- `instalado`: Instalado en una unidad
- `activo`: Con servicio activo
- `suspendido`: Servicio suspendido por falta de pago
- `desinstalado`: Desinstalado de la unidad
- `inactivo`: Sin servicio
- `baja`: Dado de baja del sistema

---

#### `GET /api/v1/devices/`

**Listar dispositivos del cliente**

Lista todos los dispositivos asignados al cliente autenticado.

**Headers:** `Authorization: Bearer {access_token}`

**Query Parameters (opcionales):**

- `status` (string): Filtrar por estado (nuevo, asignado, instalado, activo, etc.)
- `active` (boolean): Filtrar por estado de servicio activo

**Response:** `200 OK`

```json
[
  {
    "device_id": "IMEI123456789",
    "brand": "Teltonika",
    "model": "FMB120",
    "firmware_version": "03.28.07",
    "status": "activo",
    "active": true,
    "client_id": "uuid",
    "notes": null,
    "created_at": "2024-11-08T10:00:00Z",
    "updated_at": "2024-11-08T12:00:00Z"
  }
]
```

---

#### `GET /api/v1/devices/{device_id}`

**Obtener detalles de un dispositivo**

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "device_id": "IMEI123456789",
  "brand": "Teltonika",
  "model": "FMB120",
  "firmware_version": "03.28.07",
  "status": "instalado",
  "active": false,
  "client_id": "uuid",
  "notes": "Instalado en camioneta Toyota Hilux",
  "created_at": "2024-11-08T10:00:00Z",
  "updated_at": "2024-11-08T11:30:00Z"
}
```

---

#### `PATCH /api/v1/devices/{device_id}`

**Actualizar dispositivo**

Actualiza información del dispositivo (firmware, notas, etc.).

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "firmware_version": "03.28.08",
  "notes": "Firmware actualizado remotamente"
}
```

**Response:** `200 OK`

```json
{
  "device_id": "IMEI123456789",
  "brand": "Teltonika",
  "model": "FMB120",
  "firmware_version": "03.28.08",
  "status": "activo",
  "active": true,
  "client_id": "uuid",
  "notes": "Firmware actualizado remotamente",
  "updated_at": "2024-11-08T14:00:00Z"
}
```

---

#### `PATCH /api/v1/devices/{device_id}/status`

**Cambiar estado del dispositivo**

Actualiza el estado operativo del dispositivo.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "new_status": "suspendido",
  "reason": "Falta de pago del servicio mensual"
}
```

**Response:** `200 OK`

```json
{
  "device_id": "IMEI123456789",
  "old_status": "activo",
  "new_status": "suspendido",
  "updated_at": "2024-11-08T15:00:00Z"
}
```

---

#### `DELETE /api/v1/devices/{device_id}`

**Eliminar dispositivo** (Soft delete)

Marca el dispositivo como dado de baja.

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "message": "Dispositivo IMEI123456789 dado de baja exitosamente"
}
```

---

## 7. Eventos de Dispositivos (`/device-events`)

Historial de auditoría de todos los cambios en dispositivos.

### 🔒 Todos requieren autenticación

#### `GET /api/v1/device-events/`

**Listar eventos de dispositivos**

**Headers:** `Authorization: Bearer {access_token}`

**Query Parameters (opcionales):**

- `device_id` (string): Filtrar por dispositivo específico
- `event_type` (string): Filtrar por tipo de evento
- `limit` (int, default=100): Límite de resultados

**Response:** `200 OK`

```json
[
  {
    "id": "uuid",
    "device_id": "IMEI123456789",
    "event_type": "creado",
    "old_status": null,
    "new_status": "nuevo",
    "performed_by": "uuid-user",
    "event_details": "Dispositivo Teltonika FMB120 registrado en inventario",
    "timestamp": "2024-11-08T10:00:00Z"
  },
  {
    "id": "uuid",
    "device_id": "IMEI123456789",
    "event_type": "asignado",
    "old_status": "nuevo",
    "new_status": "asignado",
    "performed_by": "uuid-user",
    "event_details": "Dispositivo asignado al cliente Mi Empresa S.A.",
    "timestamp": "2024-11-08T10:30:00Z"
  }
]
```

**Tipos de eventos:**

- `creado`: Dispositivo registrado
- `asignado`: Asignado a cliente
- `instalado`: Instalado en unidad
- `desinstalado`: Desinstalado de unidad
- `activado`: Servicio activado
- `suspendido`: Servicio suspendido
- `actualizado`: Información actualizada
- `dado_de_baja`: Dispositivo eliminado

---

## 8. Unidades (`/units`)

Gestión de vehículos, maquinaria o cualquier unidad rastreable.

### 🔒 Todos requieren autenticación

#### `POST /api/v1/units/`

**Crear nueva unidad**

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "name": "Camioneta #01",
  "type": "vehiculo",
  "identifier": "ABC-123",
  "brand": "Toyota",
  "model": "Hilux",
  "year": 2023,
  "color": "Blanco",
  "notes": "Camioneta para distribución zona norte"
}
```

**Response:** `201 Created`

```json
{
  "id": "uuid",
  "client_id": "uuid",
  "name": "Camioneta #01",
  "type": "vehiculo",
  "identifier": "ABC-123",
  "brand": "Toyota",
  "model": "Hilux",
  "year": 2023,
  "color": "Blanco",
  "notes": "Camioneta para distribución zona norte",
  "created_at": "2024-11-08T10:00:00Z",
  "updated_at": "2024-11-08T10:00:00Z",
  "deleted_at": null
}
```

**Tipos de unidad comunes:**

- `vehiculo`: Automóviles, camionetas, camiones
- `maquinaria`: Grúas, excavadoras, etc.
- `contenedor`: Contenedores de carga
- `persona`: Para rastreo personal
- `otro`: Otros tipos

---

#### `GET /api/v1/units/`

**Listar unidades**

Lista las unidades según los permisos del usuario:

- **Usuario maestro**: Ve todas las unidades del cliente
- **Usuario regular**: Solo ve las unidades asignadas a él

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
[
  {
    "id": "uuid",
    "client_id": "uuid",
    "name": "Camioneta #01",
    "type": "vehiculo",
    "identifier": "ABC-123",
    "brand": "Toyota",
    "model": "Hilux",
    "year": 2023,
    "color": "Blanco",
    "created_at": "2024-11-08T10:00:00Z"
  }
]
```

---

#### `GET /api/v1/units/{unit_id}`

**Obtener detalles de unidad con dispositivos y usuarios**

Incluye dispositivos asignados y usuarios con acceso.

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "name": "Camioneta #01",
  "type": "vehiculo",
  "identifier": "ABC-123",
  "brand": "Toyota",
  "model": "Hilux",
  "year": 2023,
  "devices": [
    {
      "device_id": "IMEI123456789",
      "brand": "Teltonika",
      "model": "FMB120",
      "status": "activo",
      "installed_at": "2024-11-08T11:00:00Z"
    }
  ],
  "assigned_users": [
    {
      "user_id": "uuid",
      "email": "conductor@miempresa.com",
      "full_name": "Juan Pérez",
      "role": "viewer",
      "assigned_at": "2024-11-08T10:30:00Z"
    }
  ]
}
```

---

#### `PATCH /api/v1/units/{unit_id}`

**Actualizar unidad**

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "name": "Camioneta #01 (Renovada)",
  "color": "Gris",
  "notes": "Se cambió el color del vehículo"
}
```

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "name": "Camioneta #01 (Renovada)",
  "color": "Gris",
  "notes": "Se cambió el color del vehículo",
  "updated_at": "2024-11-08T12:00:00Z"
}
```

---

#### `DELETE /api/v1/units/{unit_id}`

**Eliminar unidad** (Soft delete)

Marca la unidad como eliminada. Solo usuarios maestros o con rol "admin" en la unidad.

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "message": "Unidad Camioneta #01 eliminada exitosamente"
}
```

---

## 9. Asignación Unidad-Dispositivo (`/unit-devices`)

Gestión de instalaciones de dispositivos en unidades.

### 🔒 Todos requieren autenticación

#### `POST /api/v1/unit-devices/assign`

**Instalar dispositivo en unidad**

Asigna un dispositivo GPS a una unidad/vehículo.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "unit_id": "uuid",
  "device_id": "IMEI123456789",
  "notes": "Instalado debajo del tablero"
}
```

**Response:** `201 Created`

```json
{
  "unit_id": "uuid",
  "device_id": "IMEI123456789",
  "installed_at": "2024-11-08T11:00:00Z",
  "uninstalled_at": null,
  "notes": "Instalado debajo del tablero"
}
```

**Validaciones:**

- El dispositivo debe pertenecer al cliente
- El dispositivo no debe estar instalado en otra unidad actualmente
- El usuario debe tener permisos sobre la unidad

---

#### `POST /api/v1/unit-devices/uninstall`

**Desinstalar dispositivo de unidad**

Marca un dispositivo como desinstalado de una unidad.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "unit_id": "uuid",
  "device_id": "IMEI123456789",
  "notes": "Desinstalado para mantenimiento"
}
```

**Response:** `200 OK`

```json
{
  "unit_id": "uuid",
  "device_id": "IMEI123456789",
  "installed_at": "2024-11-08T11:00:00Z",
  "uninstalled_at": "2024-11-08T14:00:00Z",
  "notes": "Desinstalado para mantenimiento"
}
```

---

#### `GET /api/v1/unit-devices/history/{device_id}`

**Historial de instalaciones de un dispositivo**

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
[
  {
    "unit_id": "uuid",
    "unit_name": "Camioneta #01",
    "device_id": "IMEI123456789",
    "installed_at": "2024-10-01T10:00:00Z",
    "uninstalled_at": "2024-10-15T14:00:00Z",
    "notes": "Reubicado a otro vehículo"
  },
  {
    "unit_id": "uuid",
    "unit_name": "Camioneta #02",
    "device_id": "IMEI123456789",
    "installed_at": "2024-10-15T15:00:00Z",
    "uninstalled_at": null,
    "notes": "Instalación actual"
  }
]
```

---

## 10. Asignación Usuario-Unidad (`/user-units`)

Sistema de permisos granulares por unidad.

### 🔒 Todos requieren autenticación (maestro o admin de la unidad)

#### `POST /api/v1/user-units/assign`

**Asignar usuario a unidad**

Otorga permisos a un usuario sobre una unidad específica.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "unit_id": "uuid",
  "user_id": "uuid",
  "role": "viewer"
}
```

**Roles disponibles:**

- `viewer`: Solo puede ver la unidad
- `editor`: Puede ver y editar información
- `admin`: Puede ver, editar y gestionar permisos

**Response:** `201 Created`

```json
{
  "unit_id": "uuid",
  "user_id": "uuid",
  "role": "viewer",
  "assigned_at": "2024-11-08T10:00:00Z"
}
```

---

#### `DELETE /api/v1/user-units/unassign`

**Desasignar usuario de unidad**

Revoca los permisos de un usuario sobre una unidad.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "unit_id": "uuid",
  "user_id": "uuid"
}
```

**Response:** `200 OK`

```json
{
  "message": "Usuario desasignado de la unidad exitosamente"
}
```

---

#### `GET /api/v1/user-units/{unit_id}/users`

**Listar usuarios asignados a una unidad**

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
[
  {
    "user_id": "uuid",
    "email": "conductor@miempresa.com",
    "full_name": "Juan Pérez",
    "role": "viewer",
    "assigned_at": "2024-11-08T10:00:00Z"
  }
]
```

---

## 11. Servicios (`/services`) - Legacy

Activación y gestión de servicios de rastreo.

### 🔒 Todos requieren autenticación

#### `POST /api/v1/services/activate`

**Activar servicio de rastreo**

Activa un servicio de rastreo para un dispositivo según un plan.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "device_id": "IMEI123456789",
  "plan_id": "uuid",
  "subscription_type": "monthly"
}
```

**Tipos de suscripción:**

- `monthly`: Pago mensual
- `annual`: Pago anual (usualmente con descuento)

**Response:** `201 Created`

```json
{
  "id": "uuid",
  "client_id": "uuid",
  "device_id": "IMEI123456789",
  "plan_id": "uuid",
  "status": "ACTIVE",
  "start_date": "2024-11-08",
  "end_date": "2024-12-08",
  "next_billing_date": "2024-12-08",
  "subscription_type": "monthly",
  "price_at_activation": "299.00",
  "currency": "MXN",
  "created_at": "2024-11-08T10:00:00Z"
}
```

**Validaciones:**

- Solo puede haber UN servicio ACTIVE por dispositivo
- El dispositivo debe pertenecer al cliente
- El plan debe existir y estar activo

---

#### `POST /api/v1/services/confirm-payment`

**Confirmar pago de servicio**

Confirma el pago de un servicio (usualmente tras confirmación de pasarela de pago).

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "device_service_id": "uuid",
  "payment_id": "uuid"
}
```

**Response:** `200 OK`

```json
{
  "message": "Pago confirmado exitosamente",
  "payment_id": "uuid",
  "status": "SUCCESS"
}
```

---

#### `GET /api/v1/services/active`

**Listar servicios activos**

Lista todos los servicios activos del cliente con detalles de dispositivo y plan.

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
[
  {
    "service_id": "uuid",
    "device_id": "IMEI123456789",
    "device_brand": "Teltonika",
    "device_model": "FMB120",
    "plan_name": "Plan Profesional",
    "plan_features": "Rastreo en tiempo real, reportes avanzados",
    "status": "ACTIVE",
    "start_date": "2024-11-08",
    "next_billing_date": "2024-12-08",
    "price": "299.00",
    "currency": "MXN"
  }
]
```

---

#### `POST /api/v1/services/cancel`

**Cancelar servicio**

Cancela un servicio activo.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "device_service_id": "uuid",
  "reason": "Cliente solicitó cancelación"
}
```

**Response:** `200 OK`

```json
{
  "message": "Servicio cancelado exitosamente",
  "service_id": "uuid",
  "status": "CANCELLED",
  "cancelled_at": "2024-11-08T15:00:00Z"
}
```

---

## 12. Planes (`/plans`)

Catálogo de planes de servicio disponibles con sus capabilities (límites y features).

> **Concepto Clave**: Las **capabilities** son la fuente de verdad para determinar qué puede hacer una organización. Ver [docs/api/plans.md](docs/api/plans.md) para detalles completos.

### 🔓 Público (no requiere autenticación)

#### `GET /api/v1/plans/`

**Listar planes disponibles con capabilities**

Obtiene el catálogo completo de planes y sus capabilities.

**Response:** `200 OK`

```json
[
  {
    "id": "uuid",
    "name": "Plan Básico",
    "description": "Rastreo en tiempo real con ubicación precisa",
    "price_monthly": "199.00",
    "price_yearly": "1990.00",
    "capabilities": {
      "max_devices": 10,
      "max_geofences": 5,
      "max_users": 3,
      "history_days": 30,
      "ai_features": false,
      "analytics_tools": false,
      "real_time_alerts": true
    },
    "features_description": [
      "Rastreo en tiempo real",
      "Historial de 30 días",
      "5 geocercas",
      "Alertas básicas"
    ],
    "active": true
  },
  {
    "id": "uuid",
    "name": "Plan Enterprise",
    "description": "Solución completa para flotas grandes con IA",
    "price_monthly": "599.00",
    "price_yearly": "5990.00",
    "capabilities": {
      "max_devices": 200,
      "max_geofences": 100,
      "max_users": 50,
      "history_days": 365,
      "ai_features": true,
      "analytics_tools": true,
      "custom_reports": true,
      "api_access": true,
      "priority_support": true,
      "real_time_alerts": true
    },
    "features_description": [
      "Rastreo en tiempo real",
      "Historial de 365 días",
      "100 geocercas",
      "IA y Analytics avanzado",
      "API de integración",
      "Soporte prioritario"
    ],
    "active": true
  }
]
```

### Sistema de Capabilities

Las capabilities efectivas de una organización se resuelven así:

```
organization_capability_override  (si existe)
         ??
plan_capability                   (del plan activo)
         ??
default_capability
```

Ver [docs/api/plans.md](docs/api/plans.md) para la lista completa de capabilities y su uso.

---

## 13. Órdenes (`/orders`)

Gestión de pedidos de hardware.

### 🔒 Todos requieren autenticación

#### `POST /api/v1/orders/`

**Crear nuevo pedido**

Crea un pedido de hardware con sus items.

**Headers:** `Authorization: Bearer {access_token}`

**Request:**

```json
{
  "items": [
    {
      "device_id": "IMEI123456789",
      "item_type": "hardware",
      "description": "GPS Teltonika FMB120",
      "quantity": 2,
      "unit_price": "1500.00"
    },
    {
      "device_id": null,
      "item_type": "accessory",
      "description": "Antena externa",
      "quantity": 2,
      "unit_price": "250.00"
    }
  ]
}
```

**Tipos de item:**

- `hardware`: Dispositivos GPS
- `accessory`: Accesorios (antenas, cables, etc.)
- `service`: Servicios adicionales
- `installation`: Servicio de instalación

**Response:** `201 Created`

```json
{
  "id": "uuid",
  "client_id": "uuid",
  "total_amount": "3500.00",
  "currency": "MXN",
  "status": "PENDING",
  "payment_id": "uuid",
  "created_at": "2024-11-08T10:00:00Z",
  "order_items": [
    {
      "id": "uuid",
      "device_id": "IMEI123456789",
      "item_type": "hardware",
      "description": "GPS Teltonika FMB120",
      "quantity": 2,
      "unit_price": "1500.00",
      "total_price": "3000.00"
    },
    {
      "id": "uuid",
      "device_id": null,
      "item_type": "accessory",
      "description": "Antena externa",
      "quantity": 2,
      "unit_price": "250.00",
      "total_price": "500.00"
    }
  ]
}
```

**Nota:** Se crea automáticamente un `payment` en estado `PENDING`.

---

#### `GET /api/v1/orders/`

**Listar pedidos del cliente**

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
[
  {
    "id": "uuid",
    "client_id": "uuid",
    "total_amount": "3500.00",
    "currency": "MXN",
    "status": "COMPLETED",
    "payment_id": "uuid",
    "created_at": "2024-11-08T10:00:00Z",
    "updated_at": "2024-11-08T11:00:00Z"
  }
]
```

**Estados de orden:**

- `PENDING`: Pendiente de pago
- `PROCESSING`: En procesamiento
- `COMPLETED`: Completada
- `CANCELLED`: Cancelada

---

#### `GET /api/v1/orders/{order_id}`

**Obtener detalles de un pedido**

Incluye todos los items del pedido.

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "client_id": "uuid",
  "total_amount": "3500.00",
  "currency": "MXN",
  "status": "COMPLETED",
  "payment_id": "uuid",
  "created_at": "2024-11-08T10:00:00Z",
  "order_items": [...]
}
```

---

## 14. Pagos (`/payments`)

Gestión de pagos del cliente.

### 🔒 Todos requieren autenticación

#### `GET /api/v1/payments/`

**Listar pagos del cliente**

**Headers:** `Authorization: Bearer {access_token}`

**Query Parameters (opcionales):**

- `status` (string): Filtrar por estado (PENDING, SUCCESS, FAILED, CANCELLED)

**Response:** `200 OK`

```json
[
  {
    "id": "uuid",
    "client_id": "uuid",
    "amount": "3500.00",
    "currency": "MXN",
    "status": "SUCCESS",
    "payment_method": "credit_card",
    "transaction_id": "TXN123456",
    "created_at": "2024-11-08T10:00:00Z",
    "updated_at": "2024-11-08T10:05:00Z"
  }
]
```

**Estados de pago:**

- `PENDING`: Pendiente de pago
- `SUCCESS`: Pagado exitosamente
- `FAILED`: Pago fallido
- `CANCELLED`: Cancelado

---

#### `GET /api/v1/payments/{payment_id}`

**Obtener detalles de un pago**

**Headers:** `Authorization: Bearer {access_token}`

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "client_id": "uuid",
  "amount": "3500.00",
  "currency": "MXN",
  "status": "SUCCESS",
  "payment_method": "credit_card",
  "transaction_id": "TXN123456",
  "payment_gateway": "stripe",
  "created_at": "2024-11-08T10:00:00Z",
  "updated_at": "2024-11-08T10:05:00Z"
}
```

---

## 15. Alertas y Reglas (`/alerts`, `/alert_rules`)

Gestión de reglas de alertas configurables por organización y consulta de alertas generadas.

Documentación detallada y ejemplos `curl`: [docs/api/alerts.md](docs/api/alerts.md)

### 🔒 Todos requieren autenticación

### Resumen funcional

- `POST /api/v1/alert_rules`: crea una regla y deduplica por fingerprint
- `GET /api/v1/alert_rules`: lista reglas activas de la organización autenticada
- `GET /api/v1/alert_rules/{rule_id}`: obtiene una regla activa
- `PATCH /api/v1/alert_rules/{rule_id}`: actualiza una regla y recalcula fingerprint si aplica
- `DELETE /api/v1/alert_rules/{rule_id}`: desactiva la regla (`soft delete`)
- `POST /api/v1/alert_rules/{rule_id}/units`: asigna unidades a la regla
- `DELETE /api/v1/alert_rules/{rule_id}/units`: desasigna unidades de la regla
- `GET /api/v1/alerts`: lista alertas por unidad con filtros opcionales de tipo y fecha

### Notas importantes

- Todas las consultas usan la organización del usuario autenticado
- Sin `unit_id`, `GET /api/v1/alerts` devuelve las ultimas 20 alertas de la organizacion
- Si la organización no está activa, los endpoints de listado devuelven `[]`
- Si el fingerprint ya existe, la API responde `409 Conflict` con `{ "id": "existing_rule_id", "message": "Regla ya existente" }`

---

## 🔄 Flujos de Negocio Principales

### Flujo 1: Onboarding de Nueva Organización

```
1. POST /accounts              → Registrar cuenta (onboarding)
   ↓
2. Sistema crea Organization (PENDING) + User (owner)
   ↓
3. Email enviado               → Usuario verifica email
   ↓
4. POST /auth/verify-email     → Activar cuenta
   ↓
5. Organization.status = ACTIVE
   ↓
6. POST /auth/login            → Iniciar sesión
   ↓
7. Organización puede operar según capabilities del plan
```

**Ejemplo práctico:**

```bash
# 1. Registrar organización
curl -X POST http://localhost:8100/api/v1/accounts \
  -H "Content-Type: application/json" \
  -d '{
    "account_name": "Mi Empresa S.A.",
    "name": "Carlos García",
    "email": "admin@miempresa.com",
    "password": "Password123!"
  }'

# 2. Usuario recibe email y hace clic en link
# 3. Frontend llama a verify-email con el token

# 4. Login
curl -X POST http://localhost:8100/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@miempresa.com",
    "password": "Password123!"
  }'
```

---

### Flujo 2: Agregar Dispositivo y Activar Servicio

```mermaid
1. POST /devices/              → Registrar dispositivo GPS
2. POST /units/                → Crear unidad/vehículo
3. POST /unit-devices/assign   → Instalar GPS en vehículo
4. GET  /plans/                → Ver planes disponibles
5. POST /services/activate     → Activar servicio de rastreo
6. Dispositivo ahora está rastreando
```

**Ejemplo práctico:**

```bash
# 1. Registrar dispositivo
curl -X POST http://localhost:8100/api/v1/devices/ \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "IMEI123456789",
    "brand": "Teltonika",
    "model": "FMB120",
    "firmware_version": "03.28.07"
  }'

# 2. Crear unidad
curl -X POST http://localhost:8100/api/v1/units/ \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Camioneta #01",
    "type": "vehiculo",
    "identifier": "ABC-123",
    "brand": "Toyota",
    "model": "Hilux"
  }'

# 3. Instalar GPS en vehículo
curl -X POST http://localhost:8100/api/v1/unit-devices/assign \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "unit_id": "{unit_uuid}",
    "device_id": "IMEI123456789"
  }'

# 4. Ver planes
curl -X GET http://localhost:8100/api/v1/plans/

# 5. Activar servicio
curl -X POST http://localhost:8100/api/v1/services/activate \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "IMEI123456789",
    "plan_id": "{plan_uuid}",
    "subscription_type": "monthly"
  }'
```

---

### Flujo 3: Invitar Usuario con Rol Específico

```
1. POST /users/invite           → Owner/Admin invita con rol
   ↓
2. Email enviado                → Nuevo usuario recibe invitación
   ↓
3. POST /users/accept-invitation → Usuario acepta y crea cuenta
   ↓
4. Usuario tiene rol asignado (admin/billing/member)
   ↓
5. (Si es member) POST /user-units/assign → Asignar unidades específicas
   ↓
6. Usuario opera según su rol y asignaciones
```

**Ejemplo práctico:**

```bash
# 1. Invitar usuario con rol billing (como owner/admin)
curl -X POST http://localhost:8100/api/v1/users/invite \
  -H "Authorization: Bearer {token_owner}" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "contador@miempresa.com",
    "full_name": "Ana Martínez",
    "role": "billing"
  }'

# 2. Usuario recibe email y hace clic en link
# 3. Frontend llama a accept-invitation

# 4. Invitar operador con rol member
curl -X POST http://localhost:8100/api/v1/users/invite \
  -H "Authorization: Bearer {token_owner}" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "conductor@miempresa.com",
    "full_name": "Juan Pérez",
    "role": "member"
  }'

# 5. Asignar unidades específicas al member
curl -X POST http://localhost:8100/api/v1/user-units/assign \
  -H "Authorization: Bearer {token_owner}" \
  -H "Content-Type: application/json" \
  -d '{
    "unit_id": "{unit_uuid}",
    "user_id": "{user_uuid}",
    "role": "viewer"
  }'

# 6. Usuario member solo ve unidades asignadas
curl -X GET http://localhost:8100/api/v1/units/ \
  -H "Authorization: Bearer {token_member}"
```

**Roles disponibles:**
- `owner` - Propietario (solo transferible)
- `admin` - Gestión de usuarios y configuración  
- `billing` - Gestión de pagos y suscripciones
- `member` - Acceso operativo según asignaciones

---

### Flujo 4: Compra de Hardware

```mermaid
1. POST /orders/                → Crear pedido de hardware
2. Se genera payment PENDING    → Cliente recibe info de pago
3. Cliente paga                 → (Integración con pasarela)
4. POST /payments/confirm       → Confirmar pago
5. Order cambia a COMPLETED     → Dispositivos listos para envío
```

---

## 🚨 Códigos de Error Comunes

### Errores de Autenticación

| Código             | Descripción                                  |
| ------------------ | -------------------------------------------- |
| `401 Unauthorized` | Token inválido o expirado                    |
| `403 Forbidden`    | Email no verificado o permisos insuficientes |
| `404 Not Found`    | Usuario no encontrado                        |

### Errores de Validación

| Código                     | Descripción                    |
| -------------------------- | ------------------------------ |
| `400 Bad Request`          | Datos inválidos en la petición |
| `422 Unprocessable Entity` | Error de validación de campos  |

### Errores de Negocio

| Código          | Descripción                         |
| --------------- | ----------------------------------- |
| `409 Conflict`  | Ya existe un recurso con esos datos |
| `404 Not Found` | Recurso no encontrado               |
| `403 Forbidden` | Operación no permitida              |

**Ejemplo de respuesta de error:**

```json
{
  "detail": "Ya existe un dispositivo con este device_id"
}
```

---

## 📊 Documentación Interactiva

### Swagger UI

Accede a la documentación interactiva de Swagger:

```
http://localhost:8100/docs
```

Características:

- ✅ Probar endpoints directamente desde el navegador
- ✅ Ver todos los modelos de datos
- ✅ Autenticación integrada
- ✅ Ejemplos de request/response

### ReDoc

Documentación alternativa más limpia:

```
http://localhost:8100/redoc
```

---

## 🔧 Testing y Desarrollo

### Health Check

```bash
GET /health

Response:
{
  "status": "healthy",
  "service": "siscom-admin-api"
}
```

### Variables de Entorno Requeridas

Ver [README.md](README.md) para la lista completa de variables de entorno.

**Mínimas requeridas:**

```env
# Base de datos
DB_HOST=localhost
DB_PORT=5432
DB_USER=siscom
DB_PASSWORD=changeme
DB_NAME=siscom_admin

# AWS Cognito
COGNITO_REGION=us-east-1
COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxx
COGNITO_CLIENT_SECRET=xxxxxxxxxxxxxxxxxx

# AWS SES (Emails)
SES_FROM_EMAIL=noreply@tudominio.com
SES_REGION=us-east-1

# Frontend
FRONTEND_URL=https://app.tudominio.com
```

---

## 📞 Soporte y Contacto

### Recursos Adicionales

- **Guías técnicas**: Ver carpeta `/docs/guides/`
- **Documentación de endpoints específicos**: Ver carpeta `/docs/api/`
- **Configuración de emails**: [email-configuration.md](docs/guides/email-configuration.md)
- **Setup de GitHub Actions**: [github-actions-email-setup.md](docs/guides/github-actions-email-setup.md)

### Repositorio

```
https://github.com/tu-usuario/siscom-admin-api
```

---

## 📜 Changelog

### Version 1.0.0 (2024-11-08)

**Nuevas características:**

- ✅ Sistema completo de autenticación con AWS Cognito
- ✅ Gestión multi-tenant de clientes
- ✅ Sistema de invitaciones con emails
- ✅ Gestión de dispositivos GPS con auditoría
- ✅ Sistema de unidades con permisos granulares
- ✅ Activación de servicios de rastreo
- ✅ Gestión de órdenes y pagos
- ✅ Integración con AWS SES para emails
- ✅ Deployment automatizado con GitHub Actions

**Documentación:**

- ✅ API Documentation completa
- ✅ Guías de configuración
- ✅ Ejemplos de uso

---

## 🎓 Mejores Prácticas

### Para Desarrolladores Frontend

1. **Guardar tokens de manera segura**: Usar localStorage o sessionStorage
2. **Manejar expiración de tokens**: Implementar refresh automático
3. **Validar permisos en UI**: Ocultar opciones según rol del usuario (owner/admin/billing/member)
4. **Mostrar capabilities**: Indicar límites actuales vs uso actual
5. **Advertir límites**: Notificar cuando se acercan a límites de capabilities
6. **Mostrar feedback claro**: Mensajes de error user-friendly
7. **Implementar loading states**: Durante llamadas a la API

### Para Integraciones

1. **Rate limiting**: Respetar límites de peticiones
2. **Reintentos**: Implementar exponential backoff
3. **Webhooks**: Considerar webhooks para eventos (próximamente)
4. **Paginación**: Implementar paginación para listas grandes
5. **Caché**: Cachear respuestas de catálogos (planes, etc.)

---

## 🔒 Seguridad

### Headers de Seguridad

La API implementa:

- CORS configurado correctamente
- Headers de seguridad estándar
- Rate limiting (próximamente)
- Validación de entrada exhaustiva

### Recomendaciones

1. **HTTPS en producción**: Siempre usar HTTPS
2. **Rotación de secrets**: Rotar secrets periódicamente
3. **Logs**: Monitorear logs de acceso
4. **Backups**: Realizar backups regulares de la base de datos

---

**Última actualización**: 2024-11-08  
**Versión de la API**: 1.0.0  
**Mantenido por**: SISCOM Team

---

## 🙏 Agradecimientos

Construido con:

- [FastAPI](https://fastapi.tiangolo.com/)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [AWS Cognito](https://aws.amazon.com/cognito/)
- [AWS SES](https://aws.amazon.com/ses/)
- [PostgreSQL](https://www.postgresql.org/)

---

**¿Tienes preguntas?** Consulta la documentación adicional en `/docs/` o contacta al equipo de desarrollo.

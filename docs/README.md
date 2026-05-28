# Documentación SISCOM Admin API

Bienvenido a la documentación completa de la API administrativa de SISCOM - una plataforma **SaaS B2B multi-tenant** para gestión de flotas GPS/IoT.

---

## 🏗️ Arquitectura y Modelo de Negocio

### Conceptos Fundamentales

> **Modelo conceptual**: Account = raíz comercial (billing), Organization = raíz operativa (permisos).

| Concepto | Descripción |
|----------|-------------|
| **Account** | Entidad comercial (billing, facturación) |
| **Organización** | Entidad operativa (permisos, uso diario) |
| **Suscripciones** | Contratos de servicio - una organización puede tener **múltiples** |
| **Capabilities** | Fuente de verdad para límites y features |
| **Roles** | Permisos de usuarios dentro de la organización |

### Documentación de Arquitectura

- **[Modelo Organizacional](guides/organizational-model.md)** - 📌 **LECTURA OBLIGATORIA** - Modelo conceptual completo
- **[Arquitectura del Sistema](guides/architecture.md)** - Diseño técnico y estructura del proyecto

---

## 📚 Guías de Inicio

Comienza aquí si eres nuevo en el proyecto:

- **[Guía Rápida](guides/quickstart.md)** - Configuración inicial y primeros pasos
- **[Configuración de Cognito](guides/cognito-setup.md)** - Setup de AWS Cognito para autenticación
- **[Configuración de Emails](guides/email-configuration.md)** - Setup de AWS SES para notificaciones

---

## 🔌 Documentación de Endpoints

### Autenticación y Gestión de Identidad

| Documento | Descripción |
|-----------|-------------|
| **[Autenticación](api/auth.md)** | Login, registro, tokens, verificación de email |
| **[Cuentas (Accounts)](api/accounts.md)** | Gestión de cuentas (raíz comercial) |
| **[Organizaciones](api/organizations.md)** | 📌 Gestión de organizaciones, usuarios y capabilities |
| **[Usuarios](api/users.md)** | Invitaciones, roles y gestión de usuarios |

### API Interna (Staff / GAC)

| Documento | Descripción |
|-----------|-------------|
| **[API Interna - Accounts](api/internal-accounts.md)** | Estadísticas globales del sistema (PASETO) |
| **[API Interna - Organizations](api/internal-organizations.md)** | Gestión de organizaciones (PASETO) |
| **[API Interna - Plans](api/internal-plans.md)** | 📌 Gestión de planes con operaciones compuestas (PASETO) |

### Gestión de Dispositivos y Flotas

| Documento | Descripción |
|-----------|-------------|
| **[Dispositivos](api/devices.md)** | Registro y consulta de dispositivos GPS |
| **[SIMs](api/sims.md)** | Sincronización de SIMs con KORE |
| **[Unidades](api/units.md)** | Administración de vehículos y activos |
| **[Perfiles de Unidades](api/unit-profiles.md)** | Perfiles de configuración de unidades |
| **[Asignación Unidad-Dispositivo](api/unit-devices.md)** | Instalación de GPS en unidades |
| **[Asignación Usuario-Unidad](api/user-units.md)** | Permisos de usuarios sobre unidades |
| **[Comandos](api/commands.md)** | Envío de comandos a dispositivos |
| **[User Commands](api/user-commands.md)** | Comandos críticos por usuario master |
| **[Viajes](api/trips.md)** | Gestión de viajes y rutas |
| **[Geocercas](api/geofences.md)** | CRUD de geocercas con índices H3 |

### Suscripciones y Comercial

| Documento | Descripción |
|-----------|-------------|
| **[Suscripciones](api/subscriptions.md)** | 📌 Gestión de suscripciones múltiples |
| **[Capabilities](api/capabilities.md)** | 📌 Límites y features de la organización |
| **[Planes](api/plans.md)** | Catálogo de planes disponibles (informativo) |
| **[Billing](api/billing.md)** | 📌 Resumen de facturación e invoices |
| **[Servicios](api/services.md)** | Activación de servicios (legacy) |
| **[Órdenes](api/orders.md)** | Compra de dispositivos GPS |
| **[Pagos](api/payments.md)** | Historial de pagos (raw) |

### Otros

| Documento | Descripción |
|-----------|-------------|
| **[Contacto](api/contact.md)** | Formulario de contacto público |

---

## 📋 Listado Completo de Endpoints

### Autenticación (`/api/v1/auth`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `POST` | `/login` | Login de usuario | 🌐 Público |
| `POST` | `/verify-email` | Verificar email con token | 🌐 Público |
| `POST` | `/resend-verification` | Reenviar email de verificación | 🌐 Público |
| `PATCH` | `/change-password` | Cambiar contraseña | 🔐 Cognito |
| `POST` | `/forgot-password` | Solicitar recuperación de contraseña | 🌐 Público |
| `POST` | `/reset-password` | Restablecer contraseña con token | 🌐 Público |
| `POST` | `/internal` | Obtener token PASETO interno | 🔑 Interno |
| `POST` | `/logout` | Cerrar sesión | 🔐 Cognito |
| `POST` | `/refresh` | Renovar tokens de acceso | 🌐 Público |

### Cuentas (`/api/v1/accounts`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `POST` | `/` | Onboarding rápido (crear cuenta) | 🌐 Público |
| `GET` | `/organization` | Obtener información de mi organización | 🔐 Cognito |
| `GET` | `/me` | Obtener información de mi account | 🔐 Cognito |
| `GET` | `/{account_id}` | Obtener account por ID | 🔐 Cognito |
| `PATCH` | `/{account_id}` | Actualizar perfil del account | 🔐 Cognito (Owner) |

### Usuarios (`/api/v1/users`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar usuarios de la organización | 🔐 Cognito |
| `GET` | `/me` | Obtener mi información de usuario | 🔐 Cognito |
| `POST` | `/invite` | Invitar nuevo usuario | 🔐 Cognito (Master) |
| `POST` | `/accept-invitation` | Aceptar invitación | 🌐 Público |
| `POST` | `/resend-invitation` | Reenviar invitación | 🔐 Cognito (Master) |

### Suscripciones (`/api/v1/subscriptions`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar todas las suscripciones | 🔐 Cognito |
| `GET` | `/active` | Listar suscripciones activas | 🔐 Cognito |
| `GET` | `/{subscription_id}` | Obtener detalle de suscripción | 🔐 Cognito |
| `POST` | `/{subscription_id}/cancel` | Cancelar suscripción | 🔐 Cognito (Billing) |
| `PATCH` | `/{subscription_id}/auto-renew` | Configurar auto-renovación | 🔐 Cognito (Billing) |

### Usuarios de Organización (`/api/v1/organizations/{id}/users`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar usuarios de la organización | 🔐 Cognito (Member+) |
| `POST` | `/` | Agregar usuario a la organización | 🔐 Cognito (Admin+) |
| `PATCH` | `/{user_id}` | Cambiar rol de usuario | 🔐 Cognito (Admin+) |
| `DELETE` | `/{user_id}` | Eliminar usuario de organización | 🔐 Cognito (Admin+) |

### Capabilities de Organización (`/api/v1/organizations/{id}/capabilities`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar capabilities efectivas | 🔐 Cognito (Member+) |
| `POST` | `/` | Crear/actualizar override | 🔐 Cognito (Owner) |
| `DELETE` | `/{capability_code}` | Eliminar override | 🔐 Cognito (Owner) |

### Capabilities (`/api/v1/capabilities`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Resumen de capabilities de la organización | 🔐 Cognito |
| `GET` | `/{capability_code}` | Obtener capability específica | 🔐 Cognito |
| `POST` | `/validate-limit` | Validar si se puede agregar un elemento | 🔐 Cognito |
| `GET` | `/check/{capability_code}` | Verificar si feature está habilitada | 🔐 Cognito |

### Planes (`/api/v1/plans`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar planes disponibles | 🌐 Público |
| `GET` | `/{plan_identifier}` | Obtener plan por ID o código | 🌐 Público |

### Billing (`/api/v1/billing`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/summary` | Resumen de facturación | 🔐 Cognito |
| `GET` | `/payments` | Historial de pagos | 🔐 Cognito |
| `GET` | `/invoices` | Lista de invoices (provisional) | 🔐 Cognito |

### Dispositivos (`/api/v1/devices`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `POST` | `/` | Registrar nuevo dispositivo | 🔐 Cognito / 🔑 PASETO |
| `GET` | `/` | Listar dispositivos del inventario | 🔐 Cognito / 🔑 PASETO |
| `GET` | `/my-devices` | Dispositivos asignados al usuario | 🔐 Cognito |
| `GET` | `/unassigned` | Dispositivos sin asignar | 🔐 Cognito / 🔑 PASETO |
| `GET` | `/status` | Obtener colección de estados posibles | 🌐 Público |
| `GET` | `/{device_id}` | Obtener dispositivo por ID | 🔐 Cognito / 🔑 PASETO |
| `PATCH` | `/{device_id}` | Actualizar dispositivo (incluye status) | 🔐 Cognito / 🔑 PASETO |
| `PATCH` | `/{device_id}/status` | Cambiar estado del dispositivo | 🔐 Cognito / 🔑 PASETO |
| `POST` | `/{device_id}/notes` | Agregar nota al dispositivo | 🔐 Cognito / 🔑 PASETO |
| `GET` | `/{device_id}/trips` | Viajes del dispositivo | 🔐 Cognito / 🔑 PASETO |

### SIMs (`/api/v1/sims`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `POST` | `/sync/kore` | Sincronizar SIMs de KORE hacia `sim_cards` y `sim_kore_profiles` | 🔐 Cognito / 🔑 PASETO |

### Eventos de Dispositivos (`/api/v1/device-events`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/{device_id}` | Historial de eventos del dispositivo | 🔐 Cognito |

### Unidades (`/api/v1/units`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar unidades visibles | 🔐 Cognito |
| `POST` | `/` | Crear nueva unidad | 🔐 Cognito |
| `GET` | `/{unit_id}` | Detalle de unidad | 🔐 Cognito |
| `PATCH` | `/{unit_id}` | Actualizar unidad | 🔐 Cognito |
| `DELETE` | `/{unit_id}` | Eliminar unidad (soft delete) | 🔐 Cognito |
| `GET` | `/{unit_id}/device` | Dispositivo asignado a la unidad | 🔐 Cognito |
| `POST` | `/{unit_id}/device` | Asignar dispositivo a unidad | 🔐 Cognito |
| `GET` | `/{unit_id}/profile` | Perfil de la unidad | 🔐 Cognito |
| `PATCH` | `/{unit_id}/profile` | Actualizar perfil de unidad | 🔐 Cognito |
| `POST` | `/{unit_id}/profile/vehicle` | Crear perfil de vehículo | 🔐 Cognito |
| `PATCH` | `/{unit_id}/profile/vehicle` | Actualizar perfil de vehículo | 🔐 Cognito |
| `GET` | `/{unit_id}/users` | Usuarios con acceso a la unidad | 🔐 Cognito (Master) |
| `POST` | `/{unit_id}/users` | Asignar usuario a unidad | 🔐 Cognito (Master) |
| `DELETE` | `/{unit_id}/users/{user_id}` | Revocar acceso de usuario | 🔐 Cognito (Master) |
| `GET` | `/{unit_id}/trips` | Viajes de la unidad | 🔐 Cognito |
| `POST` | `/{unit_id}/share-location` | Generar link para compartir ubicación | 🔐 Cognito |

### Asignación Unidad-Dispositivo (`/api/v1/unit-devices`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar asignaciones unidad-dispositivo | 🔐 Cognito |
| `POST` | `/` | Crear asignación unidad-dispositivo | 🔐 Cognito |

### Asignación Usuario-Unidad (`/api/v1/user-units`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar asignaciones usuario-unidad | 🔐 Cognito (Master) |
| `POST` | `/` | Asignar usuario a unidad | 🔐 Cognito (Master) |
| `DELETE` | `/{assignment_id}` | Revocar asignación | 🔐 Cognito (Master) |

### Comandos (`/api/v1/commands`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `POST` | `/` | Enviar comando a dispositivo | 🔐 Cognito / 🔑 PASETO |
| `GET` | `/` | Listar comandos enviados | 🔐 Cognito / 🔑 PASETO |
| `GET` | `/{command_id}` | Detalle de comando | 🔐 Cognito / 🔑 PASETO |
| `GET` | `/{command_id}/sync` | Sincronizar estado de comando | 🔐 Cognito / 🔑 PASETO |

### User Commands (`/api/v1/user-commands`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `POST` | `/` | Crear comando crítico sobre unidad | 🔐 Cognito (Master) |
| `GET` | `/unit/{unit_id}` | Listar comandos críticos por unidad | 🔐 Cognito (Master) |
| `POST` | `/{command_id}/sync` | Sincronizar comando crítico con KORE | 🔐 Cognito (Master) |

### Viajes (`/api/v1/trips`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar viajes | 🔐 Cognito / 🔑 PASETO |
| `GET` | `/{trip_id}` | Detalle de viaje con puntos | 🔐 Cognito / 🔑 PASETO |

### Servicios (`/api/v1/services`) - Legacy

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `POST` | `/activate` | Activar servicio para dispositivo | 🔐 Cognito |
| `POST` | `/confirm-payment` | Confirmar pago de servicio | 🔐 Cognito |
| `GET` | `/active` | Listar servicios activos | 🔐 Cognito |
| `PATCH` | `/{service_id}/cancel` | Cancelar servicio | 🔐 Cognito |

### Órdenes (`/api/v1/orders`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `POST` | `/` | Crear orden de compra | 🔐 Cognito |
| `GET` | `/` | Listar órdenes | 🔐 Cognito |
| `GET` | `/{order_id}` | Detalle de orden | 🔐 Cognito |

### Pagos (`/api/v1/payments`) - Raw

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar pagos (raw) | 🔐 Cognito |

### Contacto (`/api/v1/contact`)

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `POST` | `/send-message` | Enviar mensaje de contacto | 🌐 Público |

### API Interna - Accounts (`/api/v1/internal/accounts`) - 🔑 PASETO Only

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar todos los accounts con estadísticas | 🔑 PASETO |
| `GET` | `/stats` | Estadísticas globales (accounts, devices, users) | 🔑 PASETO |
| `GET` | `/{account_id}` | Obtener account por ID | 🔑 PASETO |
| `GET` | `/{account_id}/organizations` | Listar organizaciones del account | 🔑 PASETO |

### API Interna - Organizations (`/api/v1/internal/organizations`) - 🔑 PASETO Only

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/` | Listar todas las organizaciones | 🔑 PASETO |
| `GET` | `/stats` | Estadísticas de organizaciones por estado | 🔑 PASETO |
| `GET` | `/{organization_id}` | Obtener organización por ID | 🔑 PASETO |
| `GET` | `/{organization_id}/users` | Usuarios de una organización | 🔑 PASETO |
| `PATCH` | `/{organization_id}/status` | Cambiar estado de organización | 🔑 PASETO |

### API Interna - Plans (`/api/v1/internal/plans`) - 🔑 PASETO Only

> **Operaciones compuestas**: Crear/editar planes con capabilities y productos en una sola llamada.

| Método | Endpoint | Descripción | Auth |
|--------|----------|-------------|------|
| `GET` | `/plans` | Listar todos los planes | 🔑 PASETO |
| `POST` | `/plans` | **Crear plan completo** | 🔑 PASETO |
| `GET` | `/plans/{plan_id}` | Obtener plan por ID | 🔑 PASETO |
| `PATCH` | `/plans/{plan_id}` | **Actualizar plan completo** | 🔑 PASETO |
| `DELETE` | `/plans/{plan_id}` | Eliminar plan | 🔑 PASETO |
| `GET` | `/plans/{plan_id}/capabilities` | Listar capabilities del plan | 🔑 PASETO |
| `POST` | `/plans/{plan_id}/capabilities/{code}` | Agregar capability | 🔑 PASETO |
| `DELETE` | `/plans/{plan_id}/capabilities/{code}` | Eliminar capability | 🔑 PASETO |
| `GET` | `/plans/{plan_id}/products` | Listar productos del plan | 🔑 PASETO |
| `POST` | `/plans/{plan_id}/products/{code}` | Agregar producto al plan | 🔑 PASETO |
| `DELETE` | `/plans/{plan_id}/products/{code}` | Eliminar producto del plan | 🔑 PASETO |
| `GET` | `/products` | Listar productos del catálogo | 🔑 PASETO |
| `POST` | `/products` | Crear producto | 🔑 PASETO |
| `GET` | `/products/{product_id}` | Obtener producto por ID | 🔑 PASETO |
| `PATCH` | `/products/{product_id}` | Actualizar producto | 🔑 PASETO |
| `DELETE` | `/products/{product_id}` | Eliminar producto | 🔑 PASETO |
| `GET` | `/capabilities` | Listar capabilities disponibles | 🔑 PASETO |

### Leyenda de Autenticación

| Símbolo | Significado |
|---------|-------------|
| 🌐 Público | No requiere autenticación |
| 🔐 Cognito | Token JWT de AWS Cognito |
| 🔐 Cognito (Master) | Token Cognito + usuario maestro |
| 🔐 Cognito (Member+) | Token Cognito + rol member o superior |
| 🔐 Cognito (Admin+) | Token Cognito + rol admin o superior |
| 🔐 Cognito (Owner) | Token Cognito + rol owner |
| 🔐 Cognito (Billing) | Token Cognito + rol billing u owner |
| 🔑 PASETO | Token PASETO interno (service=gac, role=NEXUS_ADMIN) |
| 🔐 Cognito / 🔑 PASETO | Acepta cualquiera de los dos |

---

## 🏢 Modelo Multi-tenant

### Aislamiento de Datos por Organización

Cada organización tiene datos completamente aislados:

```
Token JWT → cognito_sub extraído
          ↓
  Usuario buscado por cognito_sub
          ↓
  organization_id (client_id) extraído del usuario
          ↓
  Todas las consultas filtradas por organization_id
```

### Jerarquía de Datos

```
Organization (clients)
├── Users (usuarios de la organización)
│   └── Organization_Users (roles: owner, admin, billing, member)
├── Devices (dispositivos GPS)
│   └── DeviceServices (suscripciones por dispositivo)
├── Units (vehículos/activos)
├── Subscriptions (suscripciones de la organización)
├── Orders (órdenes de compra)
└── Payments (historial de pagos)
```

---

## 🔐 Autenticación

### Tokens de Usuario (AWS Cognito)

Para usuarios finales que acceden a través de aplicaciones cliente:

```bash
Authorization: Bearer <access_token_cognito>
```

```bash
# Obtener Token
POST /api/v1/auth/login
{
  "email": "usuario@ejemplo.com",
  "password": "MiPassword123!"
}
```

### Tokens de Servicio (PASETO)

Para operaciones administrativas internas:

```bash
Authorization: Bearer <token_paseto>
```

```bash
# Obtener Token PASETO
POST /api/v1/auth/internal
{
  "email": "admin@gac-web.internal",
  "service": "gac",
  "role": "NEXUS_ADMIN"
}
```

> ⚠️ **Seguridad**: El endpoint `/auth/internal` NO debe exponerse públicamente.

---

## 📖 Endpoints Públicos

Estos endpoints **NO** requieren autenticación:

| Endpoint | Descripción |
|----------|-------------|
| `GET /` | Health check |
| `GET /api/v1/plans/` | Listar planes disponibles |
| `POST /api/v1/auth/register` | Registrar nueva cuenta (onboarding) |
| `POST /api/v1/auth/verify-email?token=...` | Verificar email |
| `POST /api/v1/auth/resend-verification` | Reenviar verificación |
| `POST /api/v1/auth/login` | Login |
| `POST /api/v1/auth/forgot-password` | Recuperar contraseña |
| `POST /api/v1/auth/reset-password` | Restablecer contraseña |
| `POST /api/v1/auth/refresh` | Renovar tokens |
| `POST /api/v1/users/accept-invitation` | Aceptar invitación |
| `POST /api/v1/contact/` | Formulario de contacto |

---

## 🚀 Flujos de Negocio Principales

### 1. Registrar Nueva Organización

```
1. Registro de Organización
   POST /api/v1/auth/register
   ↓
2. Verificación de Email
   POST /api/v1/auth/verify-email?token=...
   ↓
3. Login
   POST /api/v1/auth/login
   ↓
4. Organización activa y operativa
```

### 2. Ciclo de Vida de Suscripciones

```
1. Ver planes disponibles
   GET /api/v1/plans/
   ↓
2. Activar servicio (crea suscripción)
   POST /api/v1/services/activate
   ↓
3. Consultar suscripciones activas
   GET /api/v1/subscriptions/active
   ↓
4. Consultar capabilities efectivas
   GET /api/v1/capabilities/
   ↓
5. Renovar o cancelar
   POST /api/v1/subscriptions/{id}/cancel
```

### 3. Gestión de Usuarios y Roles

```
1. Usuario owner invita
   POST /api/v1/users/invite
   ↓
2. Invitado acepta
   POST /api/v1/users/accept-invitation
   ↓
3. Admin gestiona usuarios de organización
   POST /api/v1/organizations/{id}/users (agregar)
   PATCH /api/v1/organizations/{id}/users/{user_id} (cambiar rol)
   DELETE /api/v1/organizations/{id}/users/{user_id} (eliminar)
   ↓
4. Usuario opera según su rol
```

### 4. Gestión de Capabilities

```
1. Consultar capabilities actuales
   GET /api/v1/organizations/{id}/capabilities
   ↓
2. Crear override (promoción, acuerdo especial)
   POST /api/v1/organizations/{id}/capabilities
   ↓
3. Capability efectiva se actualiza automáticamente
   ↓
4. Eliminar override cuando expire
   DELETE /api/v1/organizations/{id}/capabilities/{code}
```

---

## 🗂️ Modelos de Datos Principales

### Organization (tabla `organizations`)

```python
id: UUID
name: str                      # Nombre de la organización
status: PENDING | ACTIVE | SUSPENDED | DELETED
# active_subscription_id: UUID  # DEPRECADO - no usar como fuente de verdad
created_at: datetime
updated_at: datetime
```

### Subscription (tabla `subscriptions`)

```python
id: UUID
client_id: UUID               # Referencia a organization
plan_id: UUID
status: ACTIVE | TRIAL | EXPIRED | CANCELLED
started_at: datetime
expires_at: datetime
cancelled_at: datetime | None
auto_renew: bool
```

### User (tabla `users`)

```python
id: UUID
client_id: UUID               # Referencia a organization
email: str
full_name: str
is_master: bool               # Legacy - complementar con roles
email_verified: bool
cognito_sub: str
```

### Roles Organizacionales

| Rol | Descripción |
|-----|-------------|
| `owner` | Propietario de la organización - permisos totales |
| `admin` | Administrador - gestión de usuarios y configuración |
| `billing` | Facturación - gestión de pagos y suscripciones |
| `member` | Miembro - acceso operativo según asignaciones |

---

## ⚙️ Configuración

### Variables de Entorno Requeridas

```bash
# Base de datos
DB_HOST=localhost
DB_PORT=5432
DB_USER=siscom
DB_PASSWORD=password
DB_NAME=siscom_admin

# AWS Cognito
AWS_REGION=us-east-1
COGNITO_USERPOOL_ID=us-east-1_XXXXXXXXX
COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
COGNITO_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# PASETO (API Interna)
PASETO_SECRET_KEY=your-secret-key-min-32-chars

# AWS SES (Emails)
SES_FROM_EMAIL=noreply@tudominio.com
SES_REGION=us-east-1

# Frontend
FRONTEND_URL=https://app.tudominio.com
```

---

## 🧪 Testing

### Scripts de Prueba

Los scripts de testing están en `scripts/testing/`:

- `test_auth_endpoints.sh` - Prueba flujos de autenticación
- `test_user_creation.sh` - Prueba creación de usuarios
- `test_password_recovery.sh` - Prueba recuperación de contraseña
- `test_invitation_resend.sh` - Prueba reenvío de invitaciones
- `test_contact_security.sh` - Prueba seguridad de contacto

---

## 📊 Documentación Interactiva

Una vez que la API esté corriendo:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## 🛠️ Desarrollo

### Ejecutar Localmente

```bash
# Con Docker
docker-compose up -d

# Sin Docker
uvicorn app.main:app --reload
```

### Ejecutar Tests

```bash
pytest -v
```

### Crear Migración

```bash
alembic revision --autogenerate -m "descripcion"
alembic upgrade head
```

---

## 📝 Notas Importantes

### Seguridad

- Los tokens de acceso (Cognito) expiran en 1 hora
- Los tokens PASETO tienen expiración configurable (default: 24h)
- Usar HTTPS en producción
- No compartir credenciales de Cognito ni PASETO_SECRET_KEY

### Límites y Capabilities

- Los límites se resuelven: `org_override ?? plan_capability ?? default`
- Un dispositivo solo puede tener UN servicio ACTIVE simultáneamente
- Los seriales e IMEIs deben ser únicos en todo el sistema
- Los emails deben ser únicos por organización

### Mejores Prácticas

- Siempre manejar errores 401 (token expirado)
- Implementar refresh token para renovar acceso
- Validar permisos de usuario según rol en frontend
- Consultar capabilities antes de operaciones con límites

---

## 🔄 Actualizaciones

### Versión 2.3.0 (Enero 2026)

- ✅ **API Internal refactorizada** - Separación clara de API Pública e Internal
- ✅ **Operaciones compuestas** - Crear/editar planes con capabilities y productos en una llamada
- ✅ Campo `is_active` en planes para activar/desactivar
- ✅ Endpoints auxiliares para ajustes puntuales (uso avanzado)
- ✅ API Pública de planes ahora solo muestra planes activos
- ✅ Renombrado de rutas: `/admin/` → `/internal/plans/`
- ✅ Documentación actualizada con nueva estructura

### Versión 2.2.0 (Enero 2026)

- ✅ CRUD completo de Plans (crear, actualizar, eliminar)
- ✅ CRUD completo de Products (crear, actualizar, eliminar)
- ✅ Gestión de plan_capabilities (agregar, actualizar, eliminar)
- ✅ Gestión de plan_products (asociar productos a planes)
- ✅ Modelo Product y PlanProduct
- ✅ Documentación de API Admin Plans (ahora Internal Plans)

### Versión 2.1.0 (Enero 2026)

- ✅ Endpoints de gestión de usuarios por organización (CRUD)
- ✅ Endpoints de gestión de capabilities por organización (overrides)
- ✅ Sistema de auditoría con `account_events`
- ✅ Reglas de negocio para roles (owner > admin > billing > member)
- ✅ Documentación actualizada de Organizations

### Versión 2.0.0 (Diciembre 2025)

- ✅ Modelo organizacional documentado
- ✅ Sistema de capabilities definido
- ✅ Roles organizacionales establecidos
- ✅ API interna como orquestador administrativo
- ✅ Suscripciones múltiples por organización

---

**Última actualización**: Enero 2026  
**Versión de documentación**: 2.3.0

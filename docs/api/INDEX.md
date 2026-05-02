# 📚 Índice de Documentación de APIs

> **SISCOM Admin API** - Documentación completa de endpoints organizados por categoría

---

## 🏠 Documentación Principal

- [**API_DOCUMENTATION.md**](../API_DOCUMENTATION.md) - Documentación general completa de la API
- [**README.md**](README.md) - Guía de la documentación

---

## 🔐 Autenticación y Autorización

### [authentication.md](./authentication.md)
Sistema completo de autenticación y autorización con JWT (Cognito) y PASETO (servicios internos).

**Endpoints principales:**
- Login y logout
- Refresh tokens
- Recuperación de contraseña
- Autenticación de servicios internos

### [auth.md](./auth.md)
Documentación detallada de endpoints de autenticación.

**Endpoints:**
- `POST /api/v1/auth/register` - Registro de cuentas
- `POST /api/v1/auth/login` - Inicio de sesión
- `POST /api/v1/auth/logout` - Cierre de sesión
- `POST /api/v1/auth/forgot-password` - Recuperación de contraseña
- `POST /api/v1/auth/reset-password` - Restablecer contraseña
- `PATCH /api/v1/auth/password` - Cambiar contraseña
- `POST /api/v1/auth/resend-verification` - Reenviar verificación
- `POST /api/v1/auth/verify-email` - Verificar email
- `POST /api/v1/auth/refresh` - Renovar tokens
- `GET /api/v1/auth/me` - Información del usuario actual
- `POST /api/v1/auth/internal` - Token para servicios internos

---

## 👥 Gestión de Cuentas y Usuarios

### [accounts.md](./accounts.md)
Gestión de Accounts (raíz comercial) y organizaciones asociadas.

**Endpoints:**
- `GET /api/v1/accounts/organization` - Organización actual
- `GET /api/v1/accounts/{account_id}` - Detalle de account
- `PATCH /api/v1/accounts/{account_id}` - Actualizar account

### [users.md](./users.md)
Gestión de usuarios, invitaciones y perfiles.

**Endpoints:**
- `GET /api/v1/users` - Listar usuarios de la organización
- `GET /api/v1/users/me` - Mi perfil
- `POST /api/v1/users/invite` - Invitar usuario
- `POST /api/v1/users/accept-invitation` - Aceptar invitación
- `POST /api/v1/users/resend-invitation` - Reenviar invitación

### [organizations.md](./organizations.md)
Gestión de organizaciones (raíz operativa).

**Endpoints:**
- `GET /api/v1/organizations` - Listar organizaciones
- `POST /api/v1/organizations` - Crear organización
- `GET /api/v1/organizations/{organization_id}` - Detalle de organización
- `PATCH /api/v1/organizations/{organization_id}` - Actualizar organización

### [organization-users.md](./organization-users.md)
Gestión de usuarios y roles dentro de organizaciones.

**Endpoints:**
- `GET /api/v1/organizations/{organization_id}/users` - Listar usuarios de organización
- `POST /api/v1/organizations/{organization_id}/users` - Agregar usuario a organización
- `PATCH /api/v1/organizations/{organization_id}/users/{user_id}` - Actualizar rol de usuario
- `DELETE /api/v1/organizations/{organization_id}/users/{user_id}` - Eliminar usuario de organización

---

## 💳 Suscripciones y Facturación

### [subscriptions.md](./subscriptions.md)
Gestión de suscripciones múltiples por organización.

**Endpoints:**
- `GET /api/v1/subscriptions` - Listar suscripciones
- `GET /api/v1/subscriptions/active` - Suscripciones activas
- `GET /api/v1/subscriptions/{subscription_id}` - Detalle de suscripción
- `POST /api/v1/subscriptions/{subscription_id}/cancel` - Cancelar suscripción
- `PATCH /api/v1/subscriptions/{subscription_id}/auto-renew` - Configurar auto-renovación

### [billing.md](./billing.md)
Resumen de facturación y pagos.

**Endpoints:**
- `GET /api/v1/billing/summary` - Resumen de facturación
- `GET /api/v1/billing/payments` - Historial de pagos
- `GET /api/v1/billing/invoices` - Lista de facturas

### [payments.md](./payments.md)
Gestión de pagos realizados.

**Endpoints:**
- `GET /api/v1/payments` - Listar pagos

### [plans.md](./plans.md)
Catálogo de planes disponibles.

**Endpoints:**
- `GET /api/v1/plans` - Listar planes disponibles
- `GET /api/v1/plans/{plan_identifier}` - Detalle de plan

---

## 🎛️ Capabilities (Límites y Features)

### [capabilities.md](./capabilities.md)
Consulta de capabilities efectivas (límites y features).

**Endpoints:**
- `GET /api/v1/capabilities` - Resumen de capabilities
- `GET /api/v1/capabilities/{capability_code}` - Capability específica
- `POST /api/v1/capabilities/validate-limit` - Validar límite

### [organization-capabilities.md](./organization-capabilities.md)
Gestión de overrides de capabilities por organización.

**Endpoints:**
- `GET /api/v1/organizations/{organization_id}/capabilities` - Listar capabilities de organización
- `POST /api/v1/organizations/{organization_id}/capabilities` - Crear/actualizar override
- `DELETE /api/v1/organizations/{organization_id}/capabilities/{capability_code}` - Eliminar override

---

## 📱 Dispositivos GPS

### [devices.md](./devices.md)
Gestión completa del inventario de dispositivos GPS.

**Endpoints:**
- `GET /api/v1/devices` - Listar dispositivos
- `POST /api/v1/devices` - Registrar dispositivo
- `GET /api/v1/devices/my-devices` - Mis dispositivos
- `GET /api/v1/devices/unassigned` - Dispositivos sin asignar
- `GET /api/v1/devices/{device_id}` - Detalle de dispositivo
- `PATCH /api/v1/devices/{device_id}` - Actualizar dispositivo
- `PATCH /api/v1/devices/{device_id}/status` - Cambiar estado
- `POST /api/v1/devices/{device_id}/notes` - Agregar nota

### [user-devices.md](./user-devices.md)
Gestión de dispositivos móviles de usuario para notificaciones push (SNS).

**Endpoints:**
- `POST /api/v1/user-devices/register` - Registrar/actualizar dispositivo push
- `POST /api/v1/user-devices/deactivate` - Desactivar dispositivo push

### [device-events.md](./device-events.md)
Historial de eventos y auditoría de dispositivos.

**Endpoints:**
- `GET /api/v1/device-events/{device_id}` - Historial de eventos

### [commands.md](./commands.md)
Envío de comandos a dispositivos GPS.

**Endpoints:**
- `POST /api/v1/commands` - Enviar comando
- `GET /api/v1/commands/device/{device_id}` - Comandos por dispositivo
- `GET /api/v1/commands/{command_id}` - Detalle de comando
- `POST /api/v1/commands/{command_id}/sync` - Sincronizar estado

---

## 🚗 Unidades y Vehículos

### [units.md](./units.md)
Gestión de unidades/vehículos/flotas.

**Endpoints:**
- `GET /api/v1/units` - Listar unidades
- `POST /api/v1/units` - Crear unidad
- `GET /api/v1/units/{unit_id}` - Detalle de unidad
- `PATCH /api/v1/units/{unit_id}` - Actualizar unidad
- `DELETE /api/v1/units/{unit_id}` - Eliminar unidad
- `GET /api/v1/units/{unit_id}/device` - Dispositivo asignado
- `POST /api/v1/units/{unit_id}/device` - Asignar dispositivo
- `GET /api/v1/units/{unit_id}/profile` - Perfil de unidad
- `PATCH /api/v1/units/{unit_id}/profile` - Actualizar perfil
- `POST /api/v1/units/{unit_id}/profile/vehicle` - Crear perfil de vehículo
- `PATCH /api/v1/units/{unit_id}/profile/vehicle` - Actualizar perfil de vehículo
- `GET /api/v1/units/{unit_id}/users` - Usuarios con acceso
- `POST /api/v1/units/{unit_id}/share-location` - Compartir ubicación

### [unit-devices.md](./unit-devices.md)
Gestión de asignaciones unidad-dispositivo.

**Endpoints:**
- `GET /api/v1/unit-devices` - Listar asignaciones
- `POST /api/v1/unit-devices` - Crear asignación
- `GET /api/v1/unit-devices/{assignment_id}` - Detalle de asignación

### [user-units.md](./user-units.md)
Gestión de permisos usuario-unidad.

**Endpoints:**
- `GET /api/v1/user-units` - Listar asignaciones usuario-unidad
- `POST /api/v1/user-units` - Asignar usuario a unidad

### [unit-profiles.md](./unit-profiles.md)
Gestión de perfiles de unidades (vehículos, personas, assets).

---

## 📍 Viajes y Trayectorias

### [trips.md](./trips.md)
Consulta de viajes y trayectorias de unidades.

**Endpoints:**
- `GET /api/v1/trips` - Listar viajes
- `GET /api/v1/trips/{trip_id}` - Detalle de viaje con puntos

---

## 🚨 Alertas y Reglas

### [alerts.md](./alerts.md)

Reglas de alerta por organizacion y consulta de alertas generadas por unidad.

**Endpoints:**

- `POST /api/v1/alert_rules` - Crear regla de alerta
- `GET /api/v1/alert_rules` - Listar reglas activas
- `GET /api/v1/alert_rules/{rule_id}` - Detalle de regla
- `PATCH /api/v1/alert_rules/{rule_id}` - Actualizar regla
- `DELETE /api/v1/alert_rules/{rule_id}` - Eliminar regla
- `POST /api/v1/alert_rules/{rule_id}/units` - Asignar unidades
- `DELETE /api/v1/alert_rules/{rule_id}/units` - Desasignar unidades
- `GET /api/v1/alerts` - Listar alertas por unidad y rango de fecha

**Notas:**

- Duplicados por fingerprint responden `409 Conflict`
- Sin `unit_id`, `GET /api/v1/alerts` devuelve las ultimas 20 alertas de la organizacion

---

## 🔑 API Platform

### [api-platform.md](./api-platform.md)

Gestión de API keys de integración, métricas de uso, logs de solicitudes y alertas operativas.

**Endpoints:**

- `POST /api/v1/api-platform/keys` - Crear API key (retorna clave en texto plano solo una vez)
- `GET /api/v1/api-platform/keys` - Listar keys (filtro por status, product_id)
- `GET /api/v1/api-platform/keys/{key_id}` - Detalle de key
- `POST /api/v1/api-platform/keys/{key_id}/revoke` - Revocar key
- `PATCH /api/v1/api-platform/keys/{key_id}` - Actualizar nombre/status
- `GET /api/v1/api-platform/usage/summary` - Resumen: active_keys, requests hoy/mes, error_rate
- `GET /api/v1/api-platform/usage/by-key` - Desglose de tráfico por key con porcentaje
- `GET /api/v1/api-platform/usage/timeseries` - Serie temporal (minute/day/month)
- `GET /api/v1/api-platform/usage/limits` - Límites del plan vs consumo actual
- `GET /api/v1/api-platform/logs` - Logs con paginación cursor-based
- `GET /api/v1/api-platform/logs/stats` - p50 latency, success rate, errors 24h
- `GET /api/v1/api-platform/throttles` - Eventos de throttling
- `POST /api/v1/api-platform/alerts` - Crear alerta (ERROR_RATE, USAGE_THRESHOLD)
- `GET /api/v1/api-platform/alerts` - Listar alertas
- `PATCH /api/v1/api-platform/alerts/{alert_id}` - Activar/desactivar alerta

**Notas:**

- `full_key` solo se retorna al crear; el backend guarda únicamente el hash SHA-256
- Logs usan paginación por cursor, no offset
- Dashboard de uso consulta tablas de agregados, no logs crudos

---

## 🗺️ Geocercas (H3)

### [geofences.md](./geofences.md)

CRUD de geocercas por organización usando índices H3.

**Endpoints:**

- `POST /api/v1/geofences` - Crear geocerca con celdas H3
- `GET /api/v1/geofences` - Listar geocercas activas
- `GET /api/v1/geofences/{geofence_id}` - Obtener detalle de geocerca
- `PATCH /api/v1/geofences/{geofence_id}` - Actualizar metadata y reemplazar H3 de forma atómica
- `DELETE /api/v1/geofences/{geofence_id}` - Desactivar geocerca (soft delete)

**Notas:**

- `PATCH` con `h3_indexes` aplica `delete + insert` en una sola transacción
- Los índices H3 duplicados en el request se deduplican

---

## 🛒 Órdenes y Servicios

### [orders.md](./orders.md)
Gestión de órdenes de compra de hardware.

**Endpoints:**
- `GET /api/v1/orders` - Listar órdenes
- `POST /api/v1/orders` - Crear orden
- `GET /api/v1/orders/{order_id}` - Detalle de orden

### [services.md](./services.md)
Activación y gestión de servicios (legacy).

**Endpoints:**
- `POST /api/v1/services/activate` - Activar servicio
- `POST /api/v1/services/confirm-payment` - Confirmar pago
- `GET /api/v1/services/active` - Servicios activos
- `PATCH /api/v1/services/{service_id}/cancel` - Cancelar servicio

---

## 📧 Comunicación

### [contact.md](./contact.md)
Formulario de contacto público.

**Endpoints:**
- `POST /api/v1/contact/send-message` - Enviar mensaje de contacto

---

## 🔧 APIs Internas (Administrativas)

> **⚠️ Requieren autenticación PASETO con rol GAC_ADMIN**

### [internal-accounts.md](./internal-accounts.md)
Gestión administrativa de accounts.

**Endpoints:**
- `GET /api/v1/internal/accounts` - Listar todos los accounts
- `GET /api/v1/internal/accounts/stats` - Estadísticas globales
- `GET /api/v1/internal/accounts/{account_id}` - Detalle de account
- `GET /api/v1/internal/accounts/{account_id}/organizations` - Organizaciones del account

### [internal-organizations.md](./internal-organizations.md)
Gestión administrativa de organizaciones.

**Endpoints:**
- `GET /api/v1/internal/organizations` - Listar todas las organizaciones
- `GET /api/v1/internal/organizations/stats` - Estadísticas de organizaciones
- `GET /api/v1/internal/organizations/{organization_id}` - Detalle de organización
- `GET /api/v1/internal/organizations/{organization_id}/users` - Usuarios de organización
- `PATCH /api/v1/internal/organizations/{organization_id}/status` - Cambiar estado

### [internal-plans.md](./internal-plans.md)
Gestión administrativa de planes y capabilities.

**Endpoints:**
- `GET /api/v1/internal/plans` - Listar planes
- `POST /api/v1/internal/plans` - Crear plan completo
- `GET /api/v1/internal/plans/{plan_id}` - Detalle de plan
- `PATCH /api/v1/internal/plans/{plan_id}` - Actualizar plan
- `DELETE /api/v1/internal/plans/{plan_id}` - Eliminar plan
- `GET /api/v1/internal/plans/{plan_id}/capabilities` - Capabilities del plan
- `POST /api/v1/internal/plans/{plan_id}/capabilities/{code}` - Agregar capability
- `DELETE /api/v1/internal/plans/{plan_id}/capabilities/{code}` - Eliminar capability

### [internal-products.md](./internal-products.md)
Gestión administrativa de productos.

**Endpoints:**
- `GET /api/v1/internal/products` - Listar productos
- `POST /api/v1/internal/products` - Crear producto
- `GET /api/v1/internal/products/{product_id}` - Detalle de producto
- `PATCH /api/v1/internal/products/{product_id}` - Actualizar producto
- `DELETE /api/v1/internal/products/{product_id}` - Eliminar producto

---

## 🗺️ Mapa de Rutas

### Rutas Públicas (sin autenticación)
```
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/forgot-password
POST   /api/v1/auth/reset-password
POST   /api/v1/auth/resend-verification
POST   /api/v1/auth/verify-email
GET    /api/v1/plans
GET    /api/v1/plans/{plan_identifier}
POST   /api/v1/contact/send-message
POST   /api/v1/users/accept-invitation
```

### Rutas Autenticadas (JWT Cognito)
```
# Auth
GET    /api/v1/auth/me
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout
PATCH  /api/v1/auth/password

# Accounts & Organizations
GET    /api/v1/accounts/organization
GET    /api/v1/accounts/{account_id}
PATCH  /api/v1/accounts/{account_id}
GET    /api/v1/organizations
POST   /api/v1/organizations
GET    /api/v1/organizations/{organization_id}
PATCH  /api/v1/organizations/{organization_id}

# Organization Users
GET    /api/v1/organizations/{organization_id}/users
POST   /api/v1/organizations/{organization_id}/users
PATCH  /api/v1/organizations/{organization_id}/users/{user_id}
DELETE /api/v1/organizations/{organization_id}/users/{user_id}

# Organization Capabilities
GET    /api/v1/organizations/{organization_id}/capabilities
POST   /api/v1/organizations/{organization_id}/capabilities
DELETE /api/v1/organizations/{organization_id}/capabilities/{capability_code}

# Users
GET    /api/v1/users
GET    /api/v1/users/me
POST   /api/v1/users/invite
POST   /api/v1/users/resend-invitation

# Capabilities
GET    /api/v1/capabilities
GET    /api/v1/capabilities/{capability_code}
POST   /api/v1/capabilities/validate-limit

# Devices
GET    /api/v1/devices
POST   /api/v1/devices
GET    /api/v1/devices/my-devices
GET    /api/v1/devices/unassigned
GET    /api/v1/devices/{device_id}
PATCH  /api/v1/devices/{device_id}
PATCH  /api/v1/devices/{device_id}/status
POST   /api/v1/devices/{device_id}/notes
GET    /api/v1/device-events/{device_id}

# Units
GET    /api/v1/units
POST   /api/v1/units
GET    /api/v1/units/{unit_id}
PATCH  /api/v1/units/{unit_id}
DELETE /api/v1/units/{unit_id}
GET    /api/v1/units/{unit_id}/device
POST   /api/v1/units/{unit_id}/device
GET    /api/v1/units/{unit_id}/profile
PATCH  /api/v1/units/{unit_id}/profile
POST   /api/v1/units/{unit_id}/profile/vehicle
PATCH  /api/v1/units/{unit_id}/profile/vehicle
GET    /api/v1/units/{unit_id}/users
POST   /api/v1/units/{unit_id}/share-location

# Unit Devices & User Units
GET    /api/v1/unit-devices
POST   /api/v1/unit-devices
GET    /api/v1/unit-devices/{assignment_id}
GET    /api/v1/user-units
POST   /api/v1/user-units

# Commands & Trips
POST   /api/v1/commands
GET    /api/v1/commands/device/{device_id}
GET    /api/v1/commands/{command_id}
POST   /api/v1/commands/{command_id}/sync
GET    /api/v1/trips
GET    /api/v1/trips/{trip_id}

# Subscriptions & Billing
GET    /api/v1/subscriptions
GET    /api/v1/subscriptions/active
GET    /api/v1/subscriptions/{subscription_id}
POST   /api/v1/subscriptions/{subscription_id}/cancel
PATCH  /api/v1/subscriptions/{subscription_id}/auto-renew
GET    /api/v1/billing/summary
GET    /api/v1/billing/payments
GET    /api/v1/billing/invoices
GET    /api/v1/payments

# Orders & Services
GET    /api/v1/orders
POST   /api/v1/orders
GET    /api/v1/orders/{order_id}
POST   /api/v1/services/activate
POST   /api/v1/services/confirm-payment
GET    /api/v1/services/active
PATCH  /api/v1/services/{service_id}/cancel

# Alerts & Alert Rules
GET    /api/v1/alerts
POST   /api/v1/alert_rules
GET    /api/v1/alert_rules
GET    /api/v1/alert_rules/{rule_id}
PATCH  /api/v1/alert_rules/{rule_id}
DELETE /api/v1/alert_rules/{rule_id}
POST   /api/v1/alert_rules/{rule_id}/units
DELETE /api/v1/alert_rules/{rule_id}/units
```

### Rutas Internas (PASETO GAC_ADMIN)
```
# Accounts
GET    /api/v1/internal/accounts
GET    /api/v1/internal/accounts/stats
GET    /api/v1/internal/accounts/{account_id}
GET    /api/v1/internal/accounts/{account_id}/organizations

# Organizations
GET    /api/v1/internal/organizations
GET    /api/v1/internal/organizations/stats
GET    /api/v1/internal/organizations/{organization_id}
GET    /api/v1/internal/organizations/{organization_id}/users
PATCH  /api/v1/internal/organizations/{organization_id}/status

# Plans
GET    /api/v1/internal/plans
POST   /api/v1/internal/plans
GET    /api/v1/internal/plans/{plan_id}
PATCH  /api/v1/internal/plans/{plan_id}
DELETE /api/v1/internal/plans/{plan_id}
GET    /api/v1/internal/plans/{plan_id}/capabilities
POST   /api/v1/internal/plans/{plan_id}/capabilities/{code}
DELETE /api/v1/internal/plans/{plan_id}/capabilities/{code}

# Products
GET    /api/v1/internal/products
POST   /api/v1/internal/products
GET    /api/v1/internal/products/{product_id}
PATCH  /api/v1/internal/products/{product_id}
DELETE /api/v1/internal/products/{product_id}
```

---

## 📖 Guías Complementarias

- [Modelo Organizacional](../guides/organizational-model.md)
- [Guía de Migración V1](../MIGRATION_GUIDE_V1.md)
- [Ciclo de Vida](../lifecyle.md)

---

**Última actualización**: 4 de abril de 2026

# 📚 Documentación de APIs - SISCOM Admin API

Bienvenido a la documentación de endpoints de la **SISCOM Admin API**.

---

## 🚀 Inicio Rápido

### Ver el Índice Completo

👉 **[INDEX.md](./INDEX.md)** - Índice completo de toda la documentación organizado por categoría

---

## 📖 Documentación por Categoría

### 🔐 Autenticación
- [authentication.md](./authentication.md) - Sistema de autenticación completo (JWT + PASETO)
- [auth.md](./auth.md) - Endpoints de autenticación detallados

### 👥 Usuarios y Organizaciones
- [accounts.md](./accounts.md) - Gestión de Accounts
- [users.md](./users.md) - Gestión de usuarios
- [organizations.md](./organizations.md) - Gestión de organizaciones
- [organization-users.md](./organization-users.md) - Usuarios y roles en organizaciones

### 💳 Facturación
- [subscriptions.md](./subscriptions.md) - Suscripciones
- [billing.md](./billing.md) - Facturación
- [payments.md](./payments.md) - Pagos
- [plans.md](./plans.md) - Planes disponibles

### 🎛️ Capabilities
- [capabilities.md](./capabilities.md) - Consulta de capabilities
- [organization-capabilities.md](./organization-capabilities.md) - Overrides de capabilities

### 📱 Dispositivos
- [devices.md](./devices.md) - Gestión de dispositivos GPS
- [user-devices.md](./user-devices.md) - Registro y desactivación de dispositivos push de usuario
- [device-events.md](./device-events.md) - Historial de eventos
- [commands.md](./commands.md) - Comandos a dispositivos

### 🚗 Unidades
- [units.md](./units.md) - Gestión de unidades/vehículos
- [unit-devices.md](./unit-devices.md) - Asignación unidad-dispositivo
- [user-units.md](./user-units.md) - Permisos usuario-unidad
- [unit-profiles.md](./unit-profiles.md) - Perfiles de unidades

### 📍 Viajes
- [trips.md](./trips.md) - Consulta de viajes y trayectorias

### 📡 Telemetría
- [telemetry.md](./telemetry.md) - Métricas agregadas por dispositivo y batch de flota

### 🚨 Alertas
- [alerts.md](./alerts.md) - Reglas de alerta y alertas generadas, con ejemplos curl

### 🗺️ Geocercas
- [geofences.md](./geofences.md) - CRUD de geocercas con indices H3

### 🛒 Órdenes
- [orders.md](./orders.md) - Órdenes de compra
- [services.md](./services.md) - Activación de servicios

### 📧 Contacto
- [contact.md](./contact.md) - Formulario de contacto

### 🔧 APIs Internas
- [internal-accounts.md](./internal-accounts.md) - Gestión administrativa de accounts
- [internal-organizations.md](./internal-organizations.md) - Gestión administrativa de organizaciones
- [internal-plans.md](./internal-plans.md) - Gestión administrativa de planes
- [internal-products.md](./internal-products.md) - Gestión administrativa de productos

---

## 🗺️ Navegación Rápida

### Por Tipo de Autenticación

**🌐 Públicos (sin auth):**
- Registro, login, recuperación de contraseña
- Catálogo de planes
- Formulario de contacto

**🔐 JWT (usuarios):**
- Gestión de organizaciones y usuarios
- Dispositivos y unidades
- Suscripciones y facturación
- Capabilities

**🔑 PASETO (servicios internos):**
- Gestión administrativa de accounts
- Gestión administrativa de organizaciones
- Gestión de planes y productos

### Por Casos de Uso

**👤 Onboarding de Usuario:**
1. [auth.md](./auth.md) - Registro y verificación
2. [accounts.md](./accounts.md) - Creación de cuenta
3. [organizations.md](./organizations.md) - Setup de organización

**📱 Gestión de Dispositivos:**
1. [devices.md](./devices.md) - Alta de dispositivos
2. [units.md](./units.md) - Creación de unidades
3. [unit-devices.md](./unit-devices.md) - Asignación
4. [device-events.md](./device-events.md) - Auditoría

**👥 Gestión de Equipo:**
1. [organization-users.md](./organization-users.md) - Agregar usuarios
2. [user-units.md](./user-units.md) - Asignar permisos
3. [users.md](./users.md) - Invitaciones

**💳 Gestión de Suscripciones:**
1. [plans.md](./plans.md) - Ver planes disponibles
2. [subscriptions.md](./subscriptions.md) - Crear suscripción
3. [billing.md](./billing.md) - Consultar facturación
4. [payments.md](./payments.md) - Ver pagos

---

## 📊 Estructura de la Documentación

Cada archivo de endpoint incluye:

- ✅ **Descripción** del propósito del endpoint
- ✅ **Headers** requeridos (autenticación)
- ✅ **Path/Query Parameters** con tipos y descripciones
- ✅ **Request Body** con ejemplos en JSON
- ✅ **Response** con códigos de estado y ejemplos
- ✅ **Permisos** necesarios (roles)
- ✅ **Errores** posibles con códigos y mensajes
- ✅ **Casos de Uso** con ejemplos curl
- ✅ **Notas Técnicas** y consideraciones

---

## 🔗 Enlaces Útiles

- [Documentación Principal](../../API_DOCUMENTATION.md)
- [Modelo Organizacional](../guides/organizational-model.md)
- [Guía de Migración](../../MIGRATION_GUIDE_V1.md)
- [Configuración AWS SES](../../CONFIGURAR_AWS_SES.md)

---

## 📝 Convenciones

### Formato de Endpoints

```
MÉTODO /api/v1/recurso/{parametro}
```

### Tipos de Respuesta

- `200 OK` - Operación exitosa
- `201 Created` - Recurso creado
- `204 No Content` - Eliminado exitosamente
- `400 Bad Request` - Error en los datos enviados
- `401 Unauthorized` - No autenticado
- `403 Forbidden` - Sin permisos
- `404 Not Found` - Recurso no encontrado
- `409 Conflict` - Conflicto (ej: duplicado)

### Roles

- `owner` - Control total
- `admin` - Gestión de usuarios y config
- `billing` - Facturación
- `member` - Acceso operativo

---

## 🆘 Soporte

¿Tienes preguntas o encontraste un error en la documentación?

- Revisa la [documentación principal](../../API_DOCUMENTATION.md)
- Consulta el código fuente en `app/api/v1/endpoints/`
- Revisa los tests en `tests/`

---

**Última actualización**: 13 de abril de 2026

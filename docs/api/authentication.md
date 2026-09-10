# Autenticación en SISCOM Admin API

## 📋 Visión General

La API de SISCOM Admin usa **3 tipos de autenticación** según el contexto y el tipo de cliente:

| Tipo | Cliente | Token | Uso |
|------|---------|-------|-----|
| **JWT (Cognito)** | Usuarios finales | `Authorization: Bearer <jwt_token>` | API pública |
| **PASETO** | Servicios internos | `Authorization: Bearer <paseto_token>` | API administrativa |
| **Público** | Cualquiera | Sin header | Endpoints informativos |

---

## 🔑 1. JWT - AWS Cognito (Usuarios Finales)

### ¿Cuándo se usa?
- Acceso de **usuarios finales** a la plataforma
- Operaciones del día a día (dispositivos, unidades, etc.)
- Gestión de organizaciones y usuarios

### ¿Cómo obtener el token?

```bash
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "usuario@empresa.com",
  "password": "MiPassword123!"
}
```

**Respuesta:**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

### Uso del token:

```bash
GET /api/v1/organizations
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Claims del JWT:

> **Tres advertencias sobre estos claims**, las tres con consecuencias de
> seguridad:
>
> - `sub` es el **sujeto del proveedor**, y es lo que la API usa para resolver al
>   usuario (`users.cognito_sub`). No es `users.external_id` —el username con el
>   que se autentica— ni `users.id`.
> - `cognito:username` **no será siempre el correo**: en los usuarios creados a
>   partir de la Fase 3 es un UUID. Ningún consumidor debe leerlo como si fuera
>   una dirección de correo.
> - Los claims `custom:*` de Cognito son **mutables desde las APIs de
>   administración**: la API los revalida contra Postgres y nunca autoriza por lo
>   que diga el token. Ver
>   [Identidad y marca](../architecture/identidad-y-marca.md).

```json
{
  "sub": "uuid-del-usuario",
  "email": "usuario@empresa.com",
  "cognito:username": "usuario@empresa.com",   // UUID en los usuarios nuevos
  "custom:organization_id": "uuid-org",
  "custom:client_id": "uuid-org",
  "token_use": "access",
  "scope": "aws.cognito.signin.user.admin",
  "auth_time": 1703123456,
  "iss": "https://cognito-idp.us-east-1.amazonaws.com/pool_id",
  "exp": 1703127056,
  "iat": 1703123456,
  "jti": "uuid-token",
  "client_id": "cognito_client_id"
}
```

---

## 🔐 2. PASETO - Servicios Internos

### ¿Cuándo se usa?
- **Aplicaciones administrativas** (GAC, Nexus Admin)
- **APIs internas** y automatizaciones
- **Operaciones administrativas** del sistema

### ¿Cómo obtener el token?

```bash
POST /api/v1/auth/internal
Content-Type: application/json

{
  "email": "admin@gac-web.internal",
  "service": "gac",
  "role": "GAC_ADMIN",
  "expires_in_hours": 24
}
```

**Respuesta:**
```json
{
  "token": "v4.local.TG35DlH7ufZj_PkbYeBQttcOENbIvdwkm1imytY53tsb...",
  "expires_at": "2024-01-15T12:00:00Z",
  "token_type": "Bearer"
}
```

### Uso del token:

```bash
GET /api/v1/internal/accounts/stats
Authorization: Bearer v4.local.TG35DlH7ufZj_PkbYeBQttcOENbIvdwkm1imytY53tsb...
```

### Claims del PASETO:
```json
{
  "token_id": "uuid-token",
  "service": "gac",
  "role": "GAC_ADMIN",
  "scope": "internal-nexus-admin",
  "email": "admin@gac-web.internal",
  "iat": "2024-01-15T00:00:00Z",
  "exp": "2024-01-15T24:00:00Z"
}
```

---

## 🔓 3. Endpoints Públicos

### ¿Cuándo se usan?
- **Catálogos informativos** (planes, precios)
- **Formularios de contacto**
- **Verificación de email**
- **Recuperación de contraseña**

### Ejemplos:

```bash
# Catálogo de planes (sin auth)
GET /api/v1/plans

# Verificación de email (usa token en URL)
GET /api/v1/auth/verify-email?token=abc123...

# Formulario de contacto
POST /api/v1/contact/send-message
```

---

## 📊 Endpoints por Tipo de Autenticación

### 🌐 **PÚBLICOS** (Sin autenticación requerida)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/v1/plans` | Listar planes disponibles |
| `GET` | `/api/v1/plans/{id}` | Detalle de plan específico |
| `POST` | `/api/v1/auth/register` | Registro de nueva cuenta |
| `POST` | `/api/v1/auth/verify-email` | Verificar email con token |
| `POST` | `/api/v1/auth/resend-verification` | Reenviar verificación |
| `POST` | `/api/v1/auth/login` | Login de usuario |
| `POST` | `/api/v1/auth/forgot-password` | Solicitar recuperación |
| `POST` | `/api/v1/auth/reset-password` | Restablecer contraseña |
| `POST` | `/api/v1/auth/refresh` | Renovar tokens |
| `POST` | `/api/v1/users/accept-invitation` | Aceptar invitación |
| `POST` | `/api/v1/contact/send-message` | Formulario de contacto |

### 🔐 **JWT (Cognito)** - Usuarios finales

| Método | Endpoint | Rol requerido | Descripción |
|--------|----------|---------------|-------------|
| `GET` | `/api/v1/accounts/organization` | Cualquier usuario | Info de organización |
| `GET` | `/api/v1/accounts/me` | Cualquier usuario | Info de account |
| `PATCH` | `/api/v1/accounts/{id}` | Owner | Actualizar account |
| `GET` | `/api/v1/organizations` | Cualquier usuario | Listar organizaciones |
| `POST` | `/api/v1/organizations` | Owner | Crear organización |
| `GET` | `/api/v1/organizations/{id}` | Member+ | Detalle organización |
| `PATCH` | `/api/v1/organizations/{id}` | Owner | Actualizar organización |
| `GET` | `/api/v1/organizations/{id}/users` | Member+ | Usuarios de org |
| `POST` | `/api/v1/organizations/{id}/users` | Admin+ | Agregar usuario |
| `PATCH` | `/api/v1/organizations/{id}/users/{id}` | Admin+ | Cambiar rol |
| `DELETE` | `/api/v1/organizations/{id}/users/{id}` | Admin+ | Eliminar usuario |
| `GET` | `/api/v1/organizations/{id}/capabilities` | Member+ | Capabilities efectivas |
| `POST` | `/api/v1/organizations/{id}/capabilities` | Owner | Crear override |
| `DELETE` | `/api/v1/organizations/{id}/capabilities/{code}` | Owner | Eliminar override |
| `GET` | `/api/v1/users` | Cualquier usuario | Listar usuarios org |
| `GET` | `/api/v1/users/me` | Cualquier usuario | Mi información |
| `POST` | `/api/v1/users/invite` | Master | Invitar usuario |
| `GET` | `/api/v1/subscriptions` | Cualquier usuario | Mis suscripciones |
| `GET` | `/api/v1/subscriptions/active` | Cualquier usuario | Suscripciones activas |
| `GET` | `/api/v1/subscriptions/{id}` | Cualquier usuario | Detalle suscripción |
| `POST` | `/api/v1/subscriptions/{id}/cancel` | Billing+ | Cancelar suscripción |
| `PATCH` | `/api/v1/subscriptions/{id}/auto-renew` | Billing+ | Auto-renovación |
| `GET` | `/api/v1/capabilities` | Cualquier usuario | Capabilities efectivas |
| `GET` | `/api/v1/capabilities/{code}` | Cualquier usuario | Capability específica |
| `POST` | `/api/v1/capabilities/validate-limit` | Cualquier usuario | Validar límite |
| `GET` | `/api/v1/capabilities/check/{code}` | Cualquier usuario | Verificar feature |
| `GET` | `/api/v1/devices` | Cualquier usuario | Dispositivos del inventario |
| `POST` | `/api/v1/devices` | Cualquier usuario | Registrar dispositivo |
| `GET` | `/api/v1/devices/my-devices` | Cualquier usuario | Mis dispositivos |
| `GET` | `/api/v1/devices/unassigned` | Cualquier usuario | Dispositivos libres |
| `GET` | `/api/v1/devices/status` | Público | Estados posibles |
| `GET` | `/api/v1/devices/{id}` | Cualquier usuario | Detalle dispositivo |
| `PATCH` | `/api/v1/devices/{id}` | Cualquier usuario | Actualizar dispositivo |
| `PATCH` | `/api/v1/devices/{id}/status` | Cualquier usuario | Cambiar estado |
| `POST` | `/api/v1/devices/{id}/notes` | Cualquier usuario | Agregar nota |
| `GET` | `/api/v1/devices/{id}/trips` | Cualquier usuario | Viajes del dispositivo |
| `GET` | `/api/v1/device-events/{device_id}` | Cualquier usuario | Eventos del dispositivo |
| `GET` | `/api/v1/units` | Cualquier usuario | Unidades visibles |
| `POST` | `/api/v1/units` | Cualquier usuario | Crear unidad |
| `GET` | `/api/v1/units/{id}` | Cualquier usuario | Detalle unidad |
| `PATCH` | `/api/v1/units/{id}` | Cualquier usuario | Actualizar unidad |
| `DELETE` | `/api/v1/units/{id}` | Cualquier usuario | Eliminar unidad |
| `GET` | `/api/v1/units/{id}/device` | Cualquier usuario | Dispositivo asignado |
| `POST` | `/api/v1/units/{id}/device` | Cualquier usuario | Asignar dispositivo |
| `GET` | `/api/v1/units/{id}/profile` | Cualquier usuario | Perfil de unidad |
| `PATCH` | `/api/v1/units/{id}/profile` | Cualquier usuario | Actualizar perfil |
| `POST` | `/api/v1/units/{id}/profile/vehicle` | Cualquier usuario | Crear perfil vehículo |
| `PATCH` | `/api/v1/units/{id}/profile/vehicle` | Cualquier usuario | Actualizar perfil vehículo |
| `GET` | `/api/v1/units/{id}/users` | Master | Usuarios con acceso |
| `POST` | `/api/v1/units/{id}/users` | Master | Asignar usuario |
| `DELETE` | `/api/v1/units/{id}/users/{id}` | Master | Revocar acceso |
| `GET` | `/api/v1/units/{id}/trips` | Cualquier usuario | Viajes de unidad |
| `POST` | `/api/v1/units/{id}/share-location` | Cualquier usuario | Compartir ubicación |
| `GET` | `/api/v1/unit-devices` | Cualquier usuario | Asignaciones unidad-dispositivo |
| `POST` | `/api/v1/unit-devices` | Cualquier usuario | Crear asignación |
| `GET` | `/api/v1/user-units` | Master | Asignaciones usuario-unidad |
| `POST` | `/api/v1/user-units` | Master | Asignar usuario a unidad |
| `DELETE` | `/api/v1/user-units/{id}` | Master | Revocar asignación |
| `POST` | `/api/v1/commands` | Cualquier usuario | Enviar comando |
| `GET` | `/api/v1/commands` | Cualquier usuario | Listar comandos |
| `GET` | `/api/v1/commands/{id}` | Cualquier usuario | Detalle comando |
| `GET` | `/api/v1/commands/{id}/sync` | Cualquier usuario | Sincronizar estado |
| `GET` | `/api/v1/commands/device/{id}` | Cualquier usuario | Comandos por dispositivo |
| `GET` | `/api/v1/trips` | Cualquier usuario | Listar viajes |
| `GET` | `/api/v1/trips/{id}` | Cualquier usuario | Detalle viaje con puntos |
| `POST` | `/api/v1/services/activate` | Cualquier usuario | Activar servicio |
| `POST` | `/api/v1/services/confirm-payment` | Cualquier usuario | Confirmar pago |
| `GET` | `/api/v1/services/active` | Cualquier usuario | Servicios activos |
| `PATCH` | `/api/v1/services/{id}/cancel` | Cualquier usuario | Cancelar servicio |
| `POST` | `/api/v1/orders` | Cualquier usuario | Crear orden |
| `GET` | `/api/v1/orders` | Cualquier usuario | Listar órdenes |
| `GET` | `/api/v1/orders/{id}` | Cualquier usuario | Detalle orden |
| `GET` | `/api/v1/payments` | Cualquier usuario | Historial de pagos |
| `GET` | `/api/v1/billing/summary` | Cualquier usuario | Resumen de facturación |
| `GET` | `/api/v1/billing/payments` | Cualquier usuario | Pagos realizados |
| `GET` | `/api/v1/billing/invoices` | Cualquier usuario | Lista de invoices |
| `PATCH` | `/api/v1/auth/change-password` | Cualquier usuario | Cambiar contraseña |
| `POST` | `/api/v1/auth/logout` | Cualquier usuario | Cerrar sesión |

### 🔑 **PASETO** - Servicios internos

| Método | Endpoint | Servicio+Rol requerido | Descripción |
|--------|----------|-------------------------|-------------|
| `GET` | `/api/v1/internal/accounts` | `gac` + `GAC_ADMIN` | Listar accounts |
| `GET` | `/api/v1/internal/accounts/stats` | `gac` + `GAC_ADMIN` | Estadísticas globales |
| `GET` | `/api/v1/internal/accounts/{id}` | `gac` + `GAC_ADMIN` | Detalle account |
| `GET` | `/api/v1/internal/accounts/{id}/organizations` | `gac` + `GAC_ADMIN` | Organizaciones del account |
| `GET` | `/api/v1/internal/organizations` | `gac` + `GAC_ADMIN` | Listar organizaciones |
| `GET` | `/api/v1/internal/organizations/stats` | `gac` + `GAC_ADMIN` | Estadísticas organizaciones |
| `GET` | `/api/v1/internal/organizations/{id}` | `gac` + `GAC_ADMIN` | Detalle organización |
| `GET` | `/api/v1/internal/organizations/{id}/users` | `gac` + `GAC_ADMIN` | Usuarios de organización |
| `PATCH` | `/api/v1/internal/organizations/{id}/status` | `gac` + `GAC_ADMIN` | Cambiar estado org |
| `GET` | `/api/v1/internal/plans` | `gac` + `GAC_ADMIN` | Listar planes |
| `POST` | `/api/v1/internal/plans` | `gac` + `GAC_ADMIN` | Crear plan completo |
| `GET` | `/api/v1/internal/plans/{id}` | `gac` + `GAC_ADMIN` | Detalle plan |
| `PATCH` | `/api/v1/internal/plans/{id}` | `gac` + `GAC_ADMIN` | Actualizar plan completo |
| `DELETE` | `/api/v1/internal/plans/{id}` | `gac` + `GAC_ADMIN` | Eliminar plan |
| `GET` | `/api/v1/internal/plans/{id}/capabilities` | `gac` + `GAC_ADMIN` | Capabilities del plan |
| `POST` | `/api/v1/internal/plans/{id}/capabilities/{code}` | `gac` + `GAC_ADMIN` | Agregar capability |
| `DELETE` | `/api/v1/internal/plans/{id}/capabilities/{code}` | `gac` + `GAC_ADMIN` | Eliminar capability |
| `GET` | `/api/v1/internal/plans/{id}/products` | `gac` + `GAC_ADMIN` | Productos del plan |
| `POST` | `/api/v1/internal/plans/{id}/products/{code}` | `gac` + `GAC_ADMIN` | Agregar producto |
| `DELETE` | `/api/v1/internal/plans/{id}/products/{code}` | `gac` + `GAC_ADMIN` | Eliminar producto |
| `GET` | `/api/v1/internal/plans/products` | `gac` + `GAC_ADMIN` | Listar productos catálogo |
| `POST` | `/api/v1/internal/plans/products` | `gac` + `GAC_ADMIN` | Crear producto |
| `GET` | `/api/v1/internal/plans/products/{id}` | `gac` + `GAC_ADMIN` | Detalle producto |
| `PATCH` | `/api/v1/internal/plans/products/{id}` | `gac` + `GAC_ADMIN` | Actualizar producto |
| `DELETE` | `/api/v1/internal/plans/products/{id}` | `gac` + `GAC_ADMIN` | Eliminar producto |
| `GET` | `/api/v1/internal/plans/capabilities` | `gac` + `GAC_ADMIN` | Listar capabilities disponibles |
| `POST` | `/api/v1/devices` | `gac` + `GAC_ADMIN` | Registrar dispositivo (admin) |
| `PATCH` | `/api/v1/devices/{id}` | `gac` + `GAC_ADMIN` | Actualizar dispositivo (admin) |
| `POST` | `/api/v1/commands` | `gac` + `GAC_ADMIN` | Enviar comando (admin) |
| `GET` | `/api/v1/commands` | `gac` + `GAC_ADMIN` | Listar comandos (admin) |
| `GET` | `/api/v1/commands/{id}` | `gac` + `GAC_ADMIN` | Detalle comando (admin) |
| `GET` | `/api/v1/commands/device/{id}` | `gac` + `GAC_ADMIN` | Comandos por dispositivo (admin) |
| `GET` | `/api/v1/trips` | `gac` + `GAC_ADMIN` | Listar viajes (admin) |
| `GET` | `/api/v1/trips/{id}` | `gac` + `GAC_ADMIN` | Detalle viaje (admin) |

---

## 🔄 Flujo de Autenticación

### Para Usuarios Finales:
```
1. POST /api/v1/auth/register (registro)
2. POST /api/v1/auth/verify-email (verificación)
3. POST /api/v1/auth/login (obtener JWT)
4. Usar JWT en Authorization header
```

### Para Servicios Internos:
```
1. POST /api/v1/auth/internal (obtener PASETO)
2. Usar PASETO en Authorization header
3. Token válido por 24 horas (configurable)
```

---

## ⚠️ Notas Importantes

- **JWT expiran en 1 hora** - usar refresh token para renovar
- **PASETO expiran en 24 horas** por defecto (configurable hasta 720h)
- **Endpoints internos requieren service="gac" y role="GAC_ADMIN"**
- **La API acepta ambos tipos** de tokens en endpoints que lo permiten
- **Tokens PASETO son para uso administrativo**, no para usuarios finales

---

**Última actualización**: Enero 2026

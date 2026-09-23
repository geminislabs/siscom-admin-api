> **Aviso (22/09/2026).** Este documento menciona `POST /api/v1/auth/internal`, que **ya no
> existe**. Firmaba un PASETO de servicio con el `role` que pidiera quien llamara, hasta 720 h,
> y como única autorización un token de Cognito válido: **cualquiera con sesión en Nexus se
> acuñaba un `GAC_ADMIN`**. Se borró en vez de restringirse porque no lo llamaba nadie — GAC
> firma sus propios tokens con `create_app_token`, detrás de su `require_roles(["admin"])`.
> Detalle en `docs/security/plano-de-control-abierto.md`.

# GeminisLabs – Mapa Completo de Endpoints (Admin API)

Este documento describe **TODOS los endpoints del sistema**, organizados por dominio funcional,
indicando su propósito dentro del **flujo completo del producto**.

> 📌 Nota clave:
> - La creación de `Account` ocurre **exclusivamente** en `auth/register`
> - `Account`, `Organization` y `User` son conceptos separados
> - Este documento es la **fuente de verdad** del flujo operativo

---

## 🔐 AUTH – Identidad y Acceso (Root del Sistema)

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Registro inicial | POST | `/api/v1/auth/register` | Crea **Account + Organization default + User master** |
| Login | POST | `/api/v1/auth/login` | Autenticación de usuario |
| Logout | POST | `/api/v1/auth/logout` | Cierre de sesión (Cognito) |
| Refresh token | POST | `/api/v1/auth/refresh` | Renovar access / id token |
| Usuario actual | GET | `/api/v1/auth/me` | Contexto activo del usuario |
| Forgot password | POST | `/api/v1/auth/forgot-password` | Solicitar código de recuperación |
| Reset password | POST | `/api/v1/auth/reset-password` | Restablecer contraseña |
| Cambiar password | PATCH | `/api/v1/auth/password` | Cambio de contraseña autenticado |
| Verificar email | POST | `/api/v1/auth/verify-email` | Confirmar email por token |
| Reenviar verificación | POST | `/api/v1/auth/resend-verification` | Reenvío de email |
| Token interno (PASETO) | POST | `/api/v1/auth/internal` | Autenticación service-to-service |

---

## 🧾 ACCOUNTS – Raíz Comercial (Billing / Contrato)

> ⚠️ No crea cuentas. Solo lectura / actualización.

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Obtener account actual | GET | `/api/v1/auth/me` | Account asociado al usuario |
| Obtener organization actual | GET | `/api/v1/accounts/organization` | Organización activa |
| Obtener account por id | GET | `/api/v1/accounts/{account_id}` | Validando acceso |
| Actualizar account | PATCH | `/api/v1/accounts/{account_id}` | Perfil progresivo (owner) |

---

## 🏢 ORGANIZATIONS – Contexto Operativo

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Listar organizaciones | GET | `/api/v1/organizations` | Del account |
| Crear organización | POST | `/api/v1/organizations` | Nueva org |
| Obtener detalle | GET | `/api/v1/organizations/{id}` | Info completa |
| Actualizar | PATCH | `/api/v1/organizations/{id}` | Datos básicos |
| Cambiar organización activa | POST | `/api/v1/organizations/{id}/switch` | Contexto UI |
| Cambiar estado | PATCH | `/api/v1/organizations/{id}/status` | Admin / internal |

---

## 👤 USERS – Usuarios Organizacionales

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Usuario actual | GET | `/api/v1/users/me` | Perfil + permisos |
| Listar usuarios | GET | `/api/v1/users` | De la organización |
| Invitar usuario | POST | `/api/v1/users/invite` | Invitación por email |
| Aceptar invitación | POST | `/api/v1/users/accept-invitation` | Alta usuario |
| Reenviar invitación | POST | `/api/v1/users/{id}/resend-invite` | Reenvío |
| Cambiar rol | PATCH | `/api/v1/users/{id}/role` | Owner / admin |
| Transferir ownership | POST | `/api/v1/users/{id}/transfer-ownership` | Cambio owner |
| Eliminar usuario | DELETE | `/api/v1/users/{id}` | Soft delete |

---

## 🚚 UNITS – Activos (Vehículos / Personas / Objetos)

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Listar unidades | GET | `/api/v1/units` | Todas |
| Crear unidad | POST | `/api/v1/units` | Validando capabilities |
| Obtener unidad | GET | `/api/v1/units/{id}` | Detalle |
| Actualizar unidad | PATCH | `/api/v1/units/{id}` | Datos básicos |
| Eliminar unidad | DELETE | `/api/v1/units/{id}` | Soft delete |
| Perfil completo | GET | `/api/v1/units/{id}/profile` | Vista unificada |
| Actualizar perfil | PATCH | `/api/v1/units/{id}/profile` | Metadata |

---

## 👥 USER–UNITS – Permisos Granulares

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Listar asignaciones | GET | `/api/v1/user-units` | Accesos |
| Asignar usuario | POST | `/api/v1/user-units` | Permiso unit |
| Revocar acceso | DELETE | `/api/v1/user-units/{id}` | Quitar acceso |

---

## 📟 DEVICES – Dispositivos GPS / IoT

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Listar dispositivos | GET | `/api/v1/devices` | Inventario |
| Crear dispositivo | POST | `/api/v1/devices` | Alta |
| Obtener dispositivo | GET | `/api/v1/devices/{device_id}` | Detalle |
| Actualizar dispositivo | PATCH | `/api/v1/devices/{device_id}` | Estado / metadata |

---

## 🔗 UNIT–DEVICES – Asignación Física

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Obtener asignación | GET | `/api/v1/units/{id}/device` | Device activo |
| Asignar / reemplazar | POST | `/api/v1/units/{id}/device` | Cambio device |

---

## ⚙️ COMMANDS – Comandos a Dispositivos

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Enviar comando | POST | `/api/v1/commands` | AT / SMS / TCP |
| Obtener comando | GET | `/api/v1/commands/{command_id}` | Estado |
| Comandos por device | GET | `/api/v1/commands/device/{id}` | Historial |

---

## 📦 SERVICES – Servicios Operativos

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Activar servicio | POST | `/api/v1/services/activate` | Alta servicio |
| Listar activos | GET | `/api/v1/services/active` | Servicios vigentes |
| Confirmar pago | POST | `/api/v1/services/confirm-payment` | Manual |
| Cancelar servicio | PATCH | `/api/v1/services/{id}/cancel` | Baja |

---

## 💳 SUBSCRIPTIONS – Suscripciones

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Listar suscripciones | GET | `/api/v1/subscriptions` | Todas |
| Activas | GET | `/api/v1/subscriptions/active` | Vigentes |
| Detalle | GET | `/api/v1/subscriptions/{id}` | Info |
| Cancelar | POST | `/api/v1/subscriptions/{id}/cancel` | Baja |
| Auto-renew | PATCH | `/api/v1/subscriptions/{id}/auto-renew` | Renovación |

---

## 🧠 CAPABILITIES – Límites y Features

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Resumen completo | GET | `/api/v1/capabilities` | Límites + features |
| Capability puntual | GET | `/api/v1/capabilities/{code}` | Valor + fuente |
| Validar límite | POST | `/api/v1/capabilities/validate-limit` | Pre-check |
| Verificar feature | GET | `/api/v1/capabilities/check/{code}` | Boolean |

---

## 🧾 BILLING – Facturación (READ-ONLY)

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Resumen | GET | `/api/v1/billing/summary` | Estado de cuenta |
| Pagos | GET | `/api/v1/billing/payments` | Historial |
| Facturas | GET | `/api/v1/billing/invoices` | Invoices (stub) |

---

## 🛒 ORDERS – Órdenes Comerciales

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Crear orden | POST | `/api/v1/orders` | Compra |
| Listar órdenes | GET | `/api/v1/orders` | Historial |
| Detalle | GET | `/api/v1/orders/{id}` | Info |

---

## 💰 PAYMENTS – Pagos

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Listar pagos | GET | `/api/v1/payments` | Historial |
| Detalle pago | GET | `/api/v1/payments/{id}` | Info |

---

## 📐 PLANS – Planes Comerciales

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Listar planes | GET | `/api/v1/plans` | Catálogo |
| Detalle plan | GET | `/api/v1/plans/{id}` | Info |

---

## 🧭 TRIPS – Histórico de Viajes

| Acción | Método | Endpoint | Descripción |
|------|------|--------|-------------|
| Listar trips | GET | `/api/v1/trips` | Global |
| Detalle trip | GET | `/api/v1/trips/{id}` | Info |
| Trips por unit | GET | `/api/v1/units/{id}/trips` | Filtro |
| Trips por device | GET | `/api/v1/devices/{id}/trips` | Filtro |

---

## 🏗 INTERNAL – Administración Global (Service Tokens)

| Acción | Método | Endpoint |
|------|------|--------|
| Listar orgs | GET | `/api/v1/internal/organizations` |
| Stats globales | GET | `/api/v1/internal/organizations/stats` |
| Detalle org | GET | `/api/v1/internal/organizations/{id}` |
| Usuarios org | GET | `/api/v1/internal/organizations/{id}/users` |
| Cambiar estado | PATCH | `/api/v1/internal/organizations/{id}/status` |

---

## 📞 CONTACT – Soporte

| Acción | Método | Endpoint |
|------|------|--------|
| Enviar contacto | POST | `/api/v1/contact` |

---

**Última actualización:** Enero 2026  
**Estado:** Documento canónico – GeminisLabs
# Módulo: Auth

## 📌 Descripción

Módulo de autenticación y gestión de sesiones.
Maneja login, logout, verificación de email, recuperación de contraseña y renovación de tokens.

> **El modelo de identidad está cambiando.** El esquema ya soporta que un mismo
> correo exista en dos marcas distintas (migración `028`, Fase 3 rebanada A);
> los flujos de abajo **todavía no lo usan**. Antes de tocar este módulo, leer
> [Identidad y marca](../identidad-y-marca.md) — sobre todo la distinción entre
> `external_id` (el username con el que se autentica) y `cognito_sub` (el sujeto
> que afirma el token), que no son el mismo identificador.

---

## 👤 Actor

- Usuario no autenticado (login, forgot-password, reset-password, verify-email)
- Usuario autenticado (logout, change-password, refresh)
- Servicios internos (generación de token PASETO)

---

## 🔌 APIs Consumidas

### 🔹 AWS Cognito (Identity Provider)

| Endpoint/Operación | Método | Uso |
|-------------------|--------|-----|
| `/.well-known/jwks.json` | GET | Obtener claves públicas para validar JWT |
| `InitiateAuth (USER_PASSWORD_AUTH)` | POST | Autenticación de usuarios |
| `InitiateAuth (REFRESH_TOKEN_AUTH)` | POST | Renovar access/id tokens |
| `GlobalSignOut` | POST | Invalidar todas las sesiones del usuario |
| `AdminSetUserPassword` | POST | Establecer nueva contraseña (reset/change) |
| `AdminCreateUser` | POST | Crear usuario en Cognito (verificación master) |
| `AdminGetUser` | POST | Verificar si usuario existe en Cognito |
| `AdminUpdateUserAttributes` | POST | Marcar email como verificado |

**Configuración requerida:**
- `COGNITO_REGION`
- `COGNITO_USER_POOL_ID`
- `COGNITO_CLIENT_ID`
- `COGNITO_CLIENT_SECRET`

---

### 🔹 AWS SES (Email Service)

| Template | Uso |
|----------|-----|
| `verification_email.html` | Envío de link de verificación de email |
| `password_reset.html` | Envío de código de 6 dígitos para reset |

**Configuración requerida:**
- `SES_FROM_EMAIL`
- `SES_REGION` (opcional, usa COGNITO_REGION)

---

### 🔹 PostgreSQL (Base de datos)

| Tabla | Operación | Uso |
|-------|-----------|-----|
| `users` | SELECT | Buscar usuario por email/cognito_sub |
| `users` | UPDATE | Actualizar last_login_at, cognito_sub, email_verified |
| `tenant_domains` | SELECT | Resolver la marca a partir del `Host` (a partir de la rebanada B) |
| `tokens_confirmacion` | INSERT | Crear token de verificación/reset |
| `tokens_confirmacion` | SELECT | Validar token |
| `tokens_confirmacion` | UPDATE | Marcar token como usado |
| `clients` | UPDATE | Activar cliente (status = ACTIVE) |

---

## 🔁 Flujo funcional

### Login (`POST /auth/login`)

```
1. Recibe email + password
2. Busca usuario en BD (verifica existencia y email_verified)
3. Llama a Cognito InitiateAuth
4. Actualiza last_login_at
5. Retorna access_token, id_token, refresh_token
```

### Forgot Password (`POST /auth/forgot-password`)

```
1. Recibe email
2. Busca usuario en BD
3. Genera código de 6 dígitos
4. Guarda en tokens_confirmacion (tipo: PASSWORD_RESET)
5. Envía email via SES con código
6. Retorna mensaje genérico (seguridad)
```

### Reset Password (`POST /auth/reset-password`)

```
1. Recibe email + código + new_password
2. Valida código en tokens_confirmacion
3. Verifica expiración y uso previo
4. Llama a Cognito AdminSetUserPassword
5. Marca código como usado
6. Retorna confirmación
```

### Verify Email (`POST /auth/verify-email`)

```
Flujo A (Usuario master con password_temp):
1. Valida token
2. Crea usuario en Cognito (si no existe)
3. Establece contraseña temporal
4. Marca email_verified en Cognito y BD
5. Activa el cliente

Flujo C (Usuario normal):
1. Valida token
2. Marca email_verified = True en BD
```

### Refresh Token (`POST /auth/refresh`)

```
1. Recibe refresh_token + email
2. Llama a Cognito InitiateAuth (REFRESH_TOKEN_AUTH)
3. Retorna nuevos access_token e id_token
```

### Logout (`POST /auth/logout`)

```
1. Obtiene access_token del header
2. Llama a Cognito GlobalSignOut
3. Retorna confirmación
```

### Change Password (`PATCH /auth/password`)

```
1. Verifica contraseña actual con Cognito
2. Llama a Cognito AdminSetUserPassword con nueva contraseña
3. Retorna confirmación
```

---

## 🏷️ Identidad por marca (Fase 3)

Detalle completo en [Identidad y marca](../identidad-y-marca.md). Lo mínimo para
trabajar en este módulo:

| Columna de `users` | Qué es | Estado |
|---|---|---|
| `external_id` | El `Username` de Cognito: **con qué se autentica**. Correo para los usuarios anteriores a la fase, UUID para los nuevos. **Opaco: no se parsea** | En el esquema desde la `028` |
| `cognito_sub` | El claim `sub`: **qué sujeto afirma el token**. Es lo que compara `deps.py` | Sin cambios |
| `brand_account_id` | La marca dueña de la credencial. **`NULL` = la marca por defecto**, no «sin marca» | En el esquema desde la `028` |
| `identity_provider` | Qué proveedor tiene la credencial. Se resuelve por cuenta (`accounts.identity_provider`), nunca por variable de entorno | En el esquema desde la `028` |

`users.email` **ya no es único global**: lo es por marca. Toda búsqueda de
credencial por correo lleva marca, o es un bug esperando al primer partner.

### Login, antes y después

```
HOY (código actual)                    REBANADA B
─────────────────────                  ──────────────────────────────────
1. email + password                    1. email + password + Host
2. User WHERE email = :email           2. Host → tenant_domains → marca
3. Cognito initiate_auth(              3. User WHERE email = :email
      USERNAME = email)                        AND brand_account_id = :marca
4. last_login_at                       4. IdentityProvider de esa cuenta
5. tokens + data token                 5. authenticate(external_id, password)
                                       6. selector de cuenta si hay varias
                                       7. tokens + data token
```

El paso 2 resuelve **apariencia y credencial**, nunca autorización: los datos
que ve el usuario los determina su subárbol (`account_path`), no la cabecera
`Host`.

---

## ⚠️ Consideraciones

- Los endpoints públicos (login, forgot-password, reset-password) no requieren autenticación
- `verify-email` y `resend-verification` usan tokens con expiración de 24h
- Los códigos de password reset expiran en 1 hora
- `forgot-password` siempre retorna el mismo mensaje por seguridad (no revela si el email existe)
- El SECRET_HASH de Cognito se calcula con HMAC-SHA256
- Los tokens PASETO se generan en `/auth/internal` para servicios

---

## 🔐 Tokens y Expiración

| Token | Expiración | Almacenamiento |
|-------|------------|----------------|
| Access Token (Cognito) | 1 hora | Cliente (frontend) |
| ID Token (Cognito) | 1 hora | Cliente (frontend) |
| Refresh Token (Cognito) | 30 días | Cliente (frontend) |
| Token de verificación | 24 horas | `tokens_confirmacion` |
| Código de reset | 1 hora | `tokens_confirmacion` |
| Token PASETO | Configurable (max 720h) | Servicio interno |

---

## 🧭 Relación C4 (preview)

- **Container:** SISCOM Admin API (FastAPI)
- **Consumes:** AWS Cognito, AWS SES, PostgreSQL
- **Consumed by:** Web App, Mobile App, Internal Services



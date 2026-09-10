# API de Cuentas (Accounts)

## Descripción

Endpoints para gestión de la **raíz comercial** del cliente. Una cuenta (`Account`) representa la entidad de facturación y billing que puede contener una o más organizaciones.

> **Nota**: El registro de nuevas cuentas se realiza en `POST /api/v1/auth/register`. Ver [API de Auth](./auth.md).

> **Referencia**: [ADR-001: Modelo Account/Organization/User](../architecture/adr/001-account-organization-user-model.md)

---

## Modelo Conceptual

```
┌─────────────────────────────────────────────────────────────┐
│                      ACCOUNT                                 │
│  - Raíz comercial (billing, facturación)                    │
│  - name: puede repetirse                                    │
│  - billing_email, country, timezone, metadata               │
└─────────────────────────┬───────────────────────────────────┘
                          │ 1:N
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    ORGANIZATION                              │
│  - Raíz operativa (permisos, uso diario)                    │
│  - name: puede repetirse globalmente                        │
│  - Pertenece a Account                                      │
└─────────────────────────┬───────────────────────────────────┘
                          │ 1:N
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                        USER                                  │
│  - email: único POR MARCA (no globalmente) *                 │
│  - Roles via OrganizationUser                               │
└─────────────────────────────────────────────────────────────┘
```

\* Hasta la migración `028` el correo era único en todo el sistema. Ahora lo
impone `UNIQUE (brand_account_id, email)`: la misma dirección puede pertenecer a
dos personas distintas, una en cada marca. Ver
[Identidad y marca](../architecture/identidad-y-marca.md).

### Regla de Oro

> **Los nombres NO son identidad. Los UUID sí.**

---

## Endpoints

### 1. Obtener Organización Actual

**GET** `/api/v1/accounts/organization`

Obtiene la información de la organización del usuario autenticado.

#### Headers

```
Authorization: Bearer <access_token>
```

#### Response 200 OK

```json
{
  "id": "223e4567-e89b-12d3-a456-426614174001",
  "account_id": "123e4567-e89b-12d3-a456-426614174000",
  "name": "Mi Empresa S.A.",
  "status": "ACTIVE",
  "billing_email": "facturacion@miempresa.com",
  "country": "MX",
  "timezone": "America/Mexico_City",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-20T15:45:00Z"
}
```

#### Errores Posibles

| Código | Detalle |
|--------|---------|
| 401 | Token no proporcionado o inválido |
| 404 | `"Organización no encontrada"` |

---

### 2. Obtener Account por ID

**GET** `/api/v1/accounts/{account_id}`

Obtiene información de un Account específico. El usuario debe tener acceso (su organización pertenece al account).

#### Headers

```
Authorization: Bearer <access_token>
```

#### Path Parameters

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `account_id` | UUID | ID del account |

#### Response 200 OK

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "account_name": "Mi Empresa S.A.",
  "status": "ACTIVE",
  "billing_email": "facturacion@miempresa.com",
  "country": "MX",
  "timezone": "America/Mexico_City",
  "metadata": {},
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-20T15:45:00Z"
}
```

#### Errores Posibles

| Código | Detalle |
|--------|---------|
| 401 | Token no proporcionado o inválido |
| 403 | `"No tienes acceso a este account"` |
| 404 | `"Account no encontrado"` |

---

### 3. Actualizar Account (Perfil Progresivo)

**PATCH** `/api/v1/accounts/{account_id}`

Actualiza el perfil del Account de forma progresiva. **Todos los campos son opcionales**.

#### Headers

```
Authorization: Bearer <access_token>
```

#### Permisos

- ✅ Solo usuarios con rol `owner` pueden modificar

#### Path Parameters

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `account_id` | UUID | ID del account |

#### Request Body

Todos los campos son opcionales:

```json
{
  "account_name": "Mi Empresa S.A. de C.V.",
  "billing_email": "nueva-facturacion@miempresa.com",
  "country": "MX",
  "timezone": "America/Mexico_City",
  "metadata": {
    "rfc": "XAXX010101000",
    "industry": "transport",
    "employees": 50
  }
}
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `account_name` | string | Nombre de la cuenta (puede repetirse) |
| `billing_email` | string | Email de facturación |
| `country` | string | Código ISO 3166-1 alpha-2 |
| `timezone` | string | Zona horaria IANA |
| `metadata` | object | Metadatos adicionales (se hace merge) |

#### Validaciones

| Validación | Resultado |
|------------|-----------|
| ❌ Unicidad de `account_name` | **NO SE VALIDA** |
| ❌ Campos fiscales obligatorios | **NO SE EXIGEN** |
| ✅ Formato de `billing_email` | SE VALIDA |
| ✅ Rol `owner` requerido | SE VALIDA |

#### Response 200 OK

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "account_name": "Mi Empresa S.A. de C.V.",
  "billing_email": "nueva-facturacion@miempresa.com",
  "country": "MX",
  "timezone": "America/Mexico_City",
  "updated_at": "2024-01-25T10:00:00Z"
}
```

#### Errores Posibles

| Código | Detalle |
|--------|---------|
| 401 | Token no proporcionado o inválido |
| 403 | `"Se requiere uno de los siguientes roles: owner"` |
| 403 | `"No tienes acceso a este account"` |
| 404 | `"Account no encontrado"` |
| 422 | Error de validación |

---

## Comportamiento del PATCH

### Merge de Metadata

Cuando se actualiza `metadata`, se hace un **merge** con el metadata existente:

```json
// Metadata existente
{
  "rfc": "XAXX010101000",
  "industry": "transport"
}

// Request PATCH
{
  "metadata": {
    "employees": 50,
    "industry": "logistics"  // Sobrescribe
  }
}

// Resultado
{
  "rfc": "XAXX010101000",      // Preservado
  "industry": "logistics",     // Sobrescrito
  "employees": 50              // Agregado
}
```

### Propagación a Organization

Algunos campos se propagan automáticamente a la Organization default:

| Campo | Se propaga |
|-------|------------|
| `account_name` | ✅ (si el nombre coincidía) |
| `billing_email` | ✅ |
| `country` | ✅ |
| `timezone` | ✅ |
| `metadata` | ❌ |

---

## Estados

### Estados de la Cuenta

| Estado | Descripción |
|--------|-------------|
| `ACTIVE` | Cuenta activa y operativa |
| `SUSPENDED` | Suspendida (falta de pago, violación TOS) |
| `DELETED` | Eliminación lógica |

### Estados de la Organización

| Estado | Descripción |
|--------|-------------|
| `ACTIVE` | Organización activa y operativa |
| `PENDING` | Pendiente de verificación (legacy) |
| `SUSPENDED` | Suspendida administrativamente |
| `DELETED` | Eliminación lógica |

> **Nota**: En el nuevo flujo, las organizaciones se crean directamente en estado `ACTIVE`.

---

## Casos de Uso

### Persona Individual

```json
POST /api/v1/auth/register

{
  "account_name": "García Personal",
  "name": "Juan García",
  "email": "juan@gmail.com",
  "password": "MiContraseña123!"
}
```

> **Resultado:**
> - Usuario: `full_name = "Juan García"`
> - Account: `name = "García Personal"`
> - Organization: `name = "ORG García Personal"` (se agrega prefijo automático)

### Familia

```json
POST /api/v1/auth/register

{
  "account_name": "Familia García López",
  "name": "María García",
  "organization_name": "Casa García",
  "email": "familia@gmail.com",
  "password": "FamiliaSegura123!"
}
```

> **Resultado:**
> - Usuario: `full_name = "María García"`
> - Account: `name = "Familia García López"`
> - Organization: `name = "Casa García"` (nombre personalizado)

### Empresa

```json
POST /api/v1/auth/register

{
  "account_name": "Transportes García S.A. de C.V.",
  "name": "Carlos García López",
  "organization_name": "Flota Norte",
  "email": "admin@transportesgarcia.com",
  "password": "EmpresaSegura123!",
  "billing_email": "facturacion@transportesgarcia.com",
  "country": "MX",
  "timezone": "America/Mexico_City"
}
```

> **Resultado:**
> - Usuario: `full_name = "Carlos García López"`
> - Account: `name = "Transportes García S.A. de C.V."`
> - Organization: `name = "Flota Norte"` (nombre personalizado)

### Completar información fiscal (después del registro)

```json
PATCH /api/v1/accounts/123e4567-...

{
  "billing_email": "facturacion@empresa.com",
  "country": "MX",
  "metadata": {
    "rfc": "ABC123456789",
    "razon_social": "Mi Empresa S.A. de C.V.",
    "regimen_fiscal": "601"
  }
}
```

---

## Flujo de Onboarding Progresivo

```
1. Registro Rápido (POST /api/v1/auth/register)
   ├── account_name: "Mi Empresa"
   ├── email: "admin@empresa.com"
   └── password: "****"
   
   → Account + Organization + User creados

2. Usuario verifica email y usa el sistema

3. Perfil Progresivo (PATCH /api/v1/accounts/{id})
   ├── billing_email: "facturacion@empresa.com"
   ├── country: "MX"
   ├── timezone: "America/Mexico_City"
   └── metadata: { rfc: "...", ... }
   
   → Account actualizado cuando el usuario lo necesite
```

---

## Notas de Seguridad

### Endpoint de Onboarding (Público)

- **No requiere autenticación**
- Se recomienda rate limiting en producción
- Validación de formato de email
- Contraseña almacenada seguramente en Cognito

### Proceso de Verificación

1. Usuario recibe email de verificación
2. Clic en link de verificación
3. `POST /api/v1/auth/verify-email?token=...`
4. Usuario marcado como `email_verified = true`
5. Puede iniciar sesión normalmente

---

## Referencias

- [API de Auth](./auth.md) - Verificación de email y login
- [API de Organizaciones (Interna)](./internal-organizations.md) - Gestión administrativa
- [ADR-001](../architecture/adr/001-account-organization-user-model.md) - Decisión arquitectónica
- [Modelo Organizacional](../guides/organizational-model.md)

---

**Última actualización**: Diciembre 2024

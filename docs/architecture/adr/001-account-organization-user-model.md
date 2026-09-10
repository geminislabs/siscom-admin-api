# ADR-001: Migración al Modelo Account / Organization / User

**Estado:** Aceptado — reemplazado en parte por [ADR-007](007-identidad-por-marca-y-handle-opaco.md)  
**Fecha:** 2024-12-29  

> La fila «`user.email` único global ✅ Requerido» de la tabla de validaciones
> **ya no es cierta** desde la migración `028` (8/09/2026): el correo es único
> **por marca**. El resto del ADR sigue vigente. El cuerpo se deja como estaba
> por la regla de inmutabilidad del [README](README.md) de este directorio.

**Autores:** Equipo de Desarrollo  
**Revisores:** -

## Contexto

El sistema original utilizaba un modelo simplificado basado en "Client" como entidad raíz que mezclaba conceptos comerciales y operativos. Este modelo presentaba las siguientes limitaciones:

1. **Mezcla de responsabilidades**: Un "Client" manejaba tanto facturación como permisos operativos
2. **Validaciones innecesarias**: Se exigía unicidad en nombres de cliente, creando fricción en el onboarding
3. **Rigidez**: No soportaba escenarios de familias o individuos con múltiples organizaciones
4. **Onboarding complejo**: Se requerían muchos campos obligatorios desde el inicio

### Problema a resolver

Necesitábamos un modelo que:
- Separara claramente responsabilidades comerciales de operativas
- Permitiera onboarding rápido y progresivo
- Soportara personas, familias y empresas con la misma flexibilidad
- Eliminara validaciones de unicidad que no aportan valor real

## Decisión

Implementamos el modelo **Account / Organization / User** con las siguientes características:

### Estructura de entidades

```
Account (Raíz Comercial)
├── Billing & Facturación
├── Información fiscal
├── Metadata comercial
└── Organizations (1:N)
    └── Organization (Raíz Operativa)
        ├── Permisos
        ├── Dispositivos
        ├── Unidades
        ├── Suscripciones
        └── Users (1:N)
            └── User
                ├── Credenciales
                └── Roles (via OrganizationUser)
```

### Regla de oro

> **Los nombres NO son identidad. Los UUID sí.**

Esta regla fundamental elimina validaciones innecesarias:

| Validación | Antes | Después |
|------------|-------|---------|
| `account_name` único | ✅ Requerido | ❌ NO requerido |
| `organization.name` único global | ✅ Requerido | ❌ NO requerido |
| `organization.name` único en account | - | ✅ Recomendado (soft) |
| `user.email` único global | ✅ Requerido | ✅ Requerido |

### Onboarding en dos fases

#### Fase 1: Onboarding rápido (POST /api/v1/auth/register)

**Request mínimo obligatorio:**
```json
{
  "account_name": "string",
  "email": "string",
  "password": "string"
}
```

**Campos opcionales:**
```json
{
  "billing_email": "string?",
  "country": "string?",
  "timezone": "string?"
}
```

**Flujo interno:**
1. Crear Account (`name = account_name`, `billing_email = billing_email ?? email`)
2. Crear Organization default (`name = account_name`, `status = ACTIVE`)
3. Crear User master (`is_master = true`, `email_verified = false`)
4. Crear membership OWNER en `organization_users`
5. Registrar usuario en Cognito
6. Enviar email de verificación (no falla el endpoint si falla el envío)

**Response:**
```json
{
  "account_id": "uuid",
  "organization_id": "uuid",
  "user_id": "uuid"
}
```

#### Fase 2: Perfil progresivo (PATCH /api/v1/accounts/{account_id})

**Request (todos opcionales):**
```json
{
  "account_name": "string?",
  "billing_email": "string?",
  "country": "string?",
  "timezone": "string?",
  "metadata": {}
}
```

**Reglas:**
- Solo usuarios con rol `owner` pueden modificar
- No se exigen campos fiscales
- No se valida unicidad por nombre
- `billing_email` puede ser único si existe

**Response:**
```json
{
  "id": "uuid",
  "account_name": "string",
  "billing_email": "string",
  "country": "string",
  "timezone": "string",
  "updated_at": "timestamp"
}
```

### Cambios en modelos ORM

#### Account
```python
class Account(SQLModel, table=True):
    id: UUID
    name: str                    # Puede repetirse
    status: AccountStatus
    billing_email: Optional[str]
    country: Optional[str]       # NUEVO
    timezone: str = "UTC"        # NUEVO
    account_metadata: dict       # NUEVO
    created_at: datetime
    updated_at: datetime
    
    # Relationships
    organizations: list[Organization]
    payments: list[Payment]
```

#### Organization
```python
class Organization(SQLModel, table=True):
    id: UUID
    account_id: UUID             # FK a Account
    name: str                    # Puede repetirse globalmente
    status: OrganizationStatus
    billing_email: Optional[str]
    country: Optional[str]
    timezone: str = "UTC"
    org_metadata: dict
    
    # Relationships
    account: Account
    users: list[User]
    subscriptions: list[Subscription]
    # ... otros
```

#### Relaciones correctas
```
Account
 └── Organizations (1:N)
      └── Users (1:N)
           └── OrganizationUser (roles)
```

### Naming consistente

| Concepto viejo | Nuevo |
|----------------|-------|
| `client` | `account` / `organization` |
| `client_id` | `account_id` / `organization_id` |
| `name` único | `name` repetible |
| `ClientStatus` | `OrganizationStatus` |

## Consecuencias

### Positivas

1. **Onboarding sin fricción**: Solo 3 campos obligatorios para empezar
2. **Flexibilidad**: Soporta personas individuales, familias y empresas
3. **Escalabilidad**: Un Account puede tener múltiples Organizations
4. **Separación de responsabilidades**: Billing en Account, operaciones en Organization
5. **Perfil progresivo**: Los usuarios completan información cuando lo necesitan
6. **Sin validaciones innecesarias**: Los nombres pueden repetirse

### Negativas

1. **Migración de datos**: Se requirió migrar estructuras existentes
2. **Actualización de código**: Múltiples archivos necesitaron actualizarse
3. **Compatibilidad**: Se mantienen algunos alias legacy temporalmente

### Neutrales

1. **Complejidad del modelo**: Más entidades pero responsabilidades claras
2. **Curva de aprendizaje**: El equipo debe entender el nuevo modelo

## Alternativas consideradas

### 1. Mantener modelo Client único
**Descartado** porque:
- No permite separación de billing y operaciones
- No escala para escenarios multi-organización
- Mantiene validaciones innecesarias

### 2. Modelo User-centric (User como raíz)
**Descartado** porque:
- No refleja la realidad comercial (las empresas tienen cuentas, no los usuarios)
- Complica la facturación B2B
- No permite que un usuario pertenezca a múltiples organizaciones fácilmente

### 3. Modelo Tenant genérico
**Descartado** porque:
- Demasiado abstracto para nuestro dominio
- Requiere más configuración
- No aporta beneficios claros sobre Account/Organization

## Implementación

### Archivos modificados

```
app/models/
├── account.py          # Agregados country, timezone, metadata
├── organization.py     # Eliminados alias legacy
└── __init__.py         # Eliminados exports legacy

app/schemas/
├── account.py          # AccountUpdate, AccountUpdateResponse
├── client.py           # OnboardingRequest, OnboardingResponse
└── __init__.py         # Nuevos exports

app/api/v1/endpoints/
├── accounts.py         # NUEVO: GET/PATCH accounts
├── accounts.py         # Onboarding rápido + gestión de accounts
├── auth.py             # Client → Organization
├── billing.py          # Actualizado
├── orders.py           # Actualizado
├── payments.py         # Actualizado
└── unit_devices.py     # Actualizado

app/api/v1/
└── router.py           # Agregado router accounts
```

### Endpoints resultantes

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/api/v1/accounts` | Onboarding rápido |
| GET | `/api/v1/accounts/organization` | Info organización actual |
| GET | `/api/v1/auth/me` | Account del usuario |
| GET | `/api/v1/accounts/{id}` | Account específico |
| PATCH | `/api/v1/accounts/{id}` | Perfil progresivo |

## Referencias

- [Modelo organizacional](../../guides/organizational-model.md)
- [Guía de migración V1](../../MIGRATION_GUIDE_V1.md)
- [Documentación de API - Accounts](../../api/accounts.md)
- [Documentación de API - Accounts](../../api/accounts.md)

## Registro de cambios

| Fecha | Versión | Cambios |
|-------|---------|---------|
| 2024-12-29 | 1.0 | Documento inicial |


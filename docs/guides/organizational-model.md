# Modelo Organizacional de SISCOM Admin API

## Visión General

Este documento define el modelo conceptual de negocio de SISCOM Admin API como una plataforma **SaaS B2B multi-tenant** para gestión de flotas GPS/IoT.

> **Nota de Arquitectura**: Este documento establece la semántica correcta del sistema. La tabla `clients` en la base de datos representa **Organizaciones** a nivel conceptual de negocio.

---

## Conceptos Fundamentales

### 0. Marca (una `Account` del árbol de cuentas)

> **Añadido en las Fases 2 y 3 (septiembre de 2026).** El esquema ya lo soporta;
> el código lo está adoptando por partes. Detalle en
> [Identidad y marca](../architecture/identidad-y-marca.md).

El sistema pasa de un operador a **varias marcas sobre el mismo despliegue**.
Una marca es una `Account` con dominio propio verificado: sus clientes entran
por `su-dominio.com`, ven su logo y sus textos legales, y no saben que
comparten instalación con nadie.

```
Geminis (marca por defecto)          Mero Mero (marca con dominio)
        │                                     │
        │  nexus.geminislabs.com              │  meromero.com
        ▼                                     ▼
   Organizaciones y usuarios            Empresa 1 ... Empresa N
                                        (cada una con sus organizaciones)
```

Tres reglas que gobiernan todo lo demás:

1. **El tenant es la `Account`**, no una entidad nueva. El árbol de reventa vive
   en `accounts.parent_account_id` + `accounts.account_path`
   (`uuid[]`, ver [ADR-006](../architecture/adr/006-camino-materializado-en-uuid.md)).
2. **El dominio determina la marca; la identidad determina los datos.** Son dos
   resoluciones independientes. El `Host` resuelve apariencia y **nunca**
   autoriza: los datos que ve un usuario los delimita su subárbol
   (`account_path @> ARRAY[:cuenta]`).
3. **La credencial pertenece a una marca.** `users.brand_account_id`, con
   `UNIQUE (brand_account_id, email)`. El mismo correo puede existir en dos
   marcas y ser dos personas distintas.

#### Consecuencia directa: el correo ya no identifica a nadie por sí solo

`users.email` **dejó de ser único global** con la migración `028`. Toda búsqueda
de credencial por correo lleva marca:

```python
db.query(User).filter(
    User.email == email,
    User.brand_account_id == marca_id,   # .is_(None) para la marca por defecto
).first()
```

Los límites comerciales de una marca —cuántos dominios, cuántas subcuentas, si
puede revender— viven en `account_capabilities`, un nivel por encima de
`organization_capabilities`, y se resuelven con **techo descendente**: ningún
descendiente puede recibir más de lo que su ancestro le concedió. Eso es lo que
hace delegable la reventa.

---

### 1. Organización (tabla `clients`)

Una **Organización** es la entidad de negocio principal. Representa una empresa, compañía o entidad que contrata los servicios de SISCOM.

```
┌─────────────────────────────────────────────────────────────┐
│                       ORGANIZACIÓN                          │
│                      (tabla: clients)                       │
├─────────────────────────────────────────────────────────────┤
│  • Tiene un nombre único                                    │
│  • Tiene un estado (PENDING, ACTIVE, SUSPENDED, DELETED)    │
│  • Puede tener MÚLTIPLES suscripciones                      │
│  • Tiene usuarios con diferentes roles                      │
│  • Posee dispositivos, unidades, órdenes, pagos             │
│  • Sus capabilities se resuelven dinámicamente              │
└─────────────────────────────────────────────────────────────┘
```

#### Estados de la Organización

| Estado | Descripción | Acceso |
|--------|-------------|--------|
| `PENDING` | Organización recién creada, email no verificado | ❌ Sin acceso |
| `ACTIVE` | Organización activa con acceso completo | ✅ Acceso total |
| `SUSPENDED` | Organización suspendida administrativamente | ❌ Sin acceso |
| `DELETED` | Organización eliminada lógicamente | ❌ Sin acceso |

---

### 2. Suscripciones (tabla `subscriptions`)

Una organización puede tener **múltiples suscripciones** a lo largo del tiempo. Las suscripciones NO son un campo fijo, sino entidades vivas con su propio ciclo de vida.

```
┌─────────────────────────────────────────────────────────────┐
│                      SUSCRIPCIONES                          │
│                   (tabla: subscriptions)                    │
├─────────────────────────────────────────────────────────────┤
│  Organización                                               │
│       │                                                     │
│       ├── Suscripción 1 (EXPIRED, Plan Básico, 2023)       │
│       ├── Suscripción 2 (CANCELLED, Plan Pro, 2024-Q1)     │
│       ├── Suscripción 3 (ACTIVE, Plan Enterprise, actual)  │
│       └── Suscripción 4 (TRIAL, Plan Premium, evaluación)  │
│                                                             │
│  La "suscripción activa" es una DERIVACIÓN lógica,         │
│  NO un campo fijo como active_subscription_id               │
└─────────────────────────────────────────────────────────────┘
```

#### Estados de Suscripción

| Estado | Descripción |
|--------|-------------|
| `ACTIVE` | Suscripción vigente y activa |
| `TRIAL` | Período de prueba |
| `EXPIRED` | Suscripción vencida por tiempo |
| `CANCELLED` | Suscripción cancelada manualmente |

#### Reglas de Negocio para Suscripciones

1. **Múltiples suscripciones activas**: Una organización PUEDE tener varias suscripciones ACTIVE simultáneamente (ej: diferentes planes para diferentes flotas)

2. **Historial completo**: El sistema mantiene el historial completo de todas las suscripciones

3. **No depender de `active_subscription_id`**: Este campo existe por compatibilidad pero NO debe usarse como fuente de verdad. El estado actual se calcula dinámicamente.

#### Estructura de Respuesta Esperada

```json
{
  "organization": {
    "id": "uuid-org",
    "name": "Transportes XYZ",
    "status": "ACTIVE"
  },
  "subscriptions": {
    "active": [
      {
        "id": "uuid-sub-1",
        "plan": { "id": "uuid-plan", "name": "Plan Enterprise" },
        "status": "ACTIVE",
        "started_at": "2024-01-01T00:00:00Z",
        "expires_at": "2025-01-01T00:00:00Z",
        "auto_renew": true
      }
    ],
    "history": [
      {
        "id": "uuid-sub-old",
        "plan": { "id": "uuid-plan-old", "name": "Plan Básico" },
        "status": "EXPIRED",
        "started_at": "2023-01-01T00:00:00Z",
        "expires_at": "2024-01-01T00:00:00Z"
      }
    ]
  }
}
```

---

### 3. Capabilities (Regla de Oro)

Las **Capabilities** son la fuente de verdad para determinar qué puede hacer una organización. Gobiernan límites, features y acceso a funcionalidades.

```
┌─────────────────────────────────────────────────────────────┐
│                    SISTEMA DE CAPABILITIES                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   Resolución de Capability Efectiva:                        │
│                                                             │
│   organization_capability_override                          │
│           ??                                                │
│   plan_capability                                           │
│                                                             │
│   (Si existe override de organización, usa ese valor;       │
│    si no, usa el valor del plan)                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### Ejemplo de Resolución

```
Escenario: Organización "Transportes XYZ" con Plan Enterprise

Plan Enterprise define:
  - max_devices: 100
  - max_geofences: 50
  - history_days: 365
  - ai_features: true

Organización tiene override:
  - max_geofences: 100  (upgrade especial)

Capabilities Efectivas Resultantes:
  - max_devices: 100      (del plan)
  - max_geofences: 100    (override de organización ✓)
  - history_days: 365     (del plan)
  - ai_features: true     (del plan)
```

#### Tipos de Capabilities

| Capability | Tipo | Descripción |
|------------|------|-------------|
| `max_devices` | Límite | Número máximo de dispositivos |
| `max_geofences` | Límite | Número máximo de geocercas |
| `max_users` | Límite | Número máximo de usuarios |
| `history_days` | Límite | Días de historial de ubicaciones |
| `ai_features` | Feature | Acceso a análisis con IA |
| `analytics_tools` | Feature | Herramientas de analytics avanzado |
| `custom_reports` | Feature | Reportes personalizados |
| `api_access` | Feature | Acceso a API de integración |
| `priority_support` | Feature | Soporte prioritario |
| `real_time_alerts` | Feature | Alertas en tiempo real |

#### Uso de Capabilities en Endpoints

Los endpoints DEBEN validar capabilities antes de permitir operaciones:

```
Ejemplo: POST /api/v1/geofences/

1. Obtener capabilities efectivas de la organización
2. Contar geocercas actuales
3. Si current_count >= max_geofences → Error 403
4. Si tiene permiso → Crear geocerca
```

---

### 4. Roles Organizacionales (tabla `organization_users`)

Los usuarios dentro de una organización tienen **roles específicos** que determinan sus permisos. El campo `is_master` es un indicador legacy que debe complementarse con roles explícitos.

```
┌─────────────────────────────────────────────────────────────┐
│                  ROLES ORGANIZACIONALES                     │
│                (tabla: organization_users)                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐  Permisos totales sobre la organización      │
│  │  OWNER   │  Único por organización                       │
│  └──────────┘  Puede transferir ownership                   │
│       │                                                     │
│  ┌──────────┐  Gestión completa (usuarios, config)         │
│  │  ADMIN   │  Puede invitar/eliminar usuarios              │
│  └──────────┘  NO puede eliminar al owner                   │
│       │                                                     │
│  ┌──────────┐  Gestión de pagos y facturación              │
│  │ BILLING  │  Ve información de suscripciones              │
│  └──────────┘  Puede realizar pagos                         │
│       │                                                     │
│  ┌──────────┐  Acceso operativo                            │
│  │  MEMBER  │  Ve dispositivos y unidades asignadas         │
│  └──────────┘  Permisos según asignaciones                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### Matriz de Permisos por Rol

| Acción | Owner | Admin | Billing | Member |
|--------|:-----:|:-----:|:-------:|:------:|
| Ver organización | ✅ | ✅ | ✅ | ✅ |
| Editar organización | ✅ | ✅ | ❌ | ❌ |
| Ver usuarios | ✅ | ✅ | ❌ | ❌ |
| Invitar usuarios | ✅ | ✅ | ❌ | ❌ |
| Eliminar usuarios | ✅ | ✅* | ❌ | ❌ |
| Ver suscripciones | ✅ | ✅ | ✅ | ❌ |
| Gestionar suscripciones | ✅ | ❌ | ✅ | ❌ |
| Ver pagos | ✅ | ❌ | ✅ | ❌ |
| Realizar pagos | ✅ | ❌ | ✅ | ❌ |
| Ver dispositivos | ✅ | ✅ | ❌ | ✅** |
| Gestionar dispositivos | ✅ | ✅ | ❌ | ❌ |
| Transferir ownership | ✅ | ❌ | ❌ | ❌ |

*Admin no puede eliminar al Owner
**Member solo ve dispositivos/unidades asignadas explícitamente

#### Migración desde `is_master`

| `is_master` | Rol Equivalente | Notas |
|-------------|-----------------|-------|
| `true` (primer usuario) | `owner` | Usuario que creó la organización |
| `true` (invitado como master) | `admin` | Usuario con permisos de gestión |
| `false` | `member` | Usuario operativo básico |

---

### 5. API Interna (PASETO) - Orquestador Administrativo

La API interna con autenticación PASETO funciona como **panel de administración** para operaciones que trascienden el contexto de una sola organización.

```
┌─────────────────────────────────────────────────────────────┐
│                    API INTERNA (PASETO)                     │
│                  Orquestador Administrativo                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  PROPÓSITO:                                                 │
│  • Administración global del sistema                        │
│  • Operaciones cross-organization                           │
│  • Panel administrativo interno (gac-web)                   │
│                                                             │
│  PUEDE:                                                     │
│  • Listar TODAS las organizaciones                          │
│  • Cambiar estado de organizaciones (ACTIVE/SUSPENDED)      │
│  • Inspeccionar suscripciones y capabilities                │
│  • Ver estadísticas globales del sistema                    │
│  • Ejecutar comandos en dispositivos                        │
│                                                             │
│  NO PUEDE:                                                  │
│  • Exponerse públicamente                                   │
│  • Usarse desde aplicaciones cliente                        │
│  • Acceder sin token PASETO válido                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### Casos de Uso del API Interna

1. **Suspender organización por falta de pago**
   ```
   PATCH /api/v1/internal/organizations/{org_id}/status?new_status=SUSPENDED
   ```

2. **Inspeccionar capabilities de una organización**
   ```
   GET /api/v1/internal/organizations/{org_id}/capabilities
   ```

3. **Ver todas las suscripciones activas en el sistema**
   ```
   GET /api/v1/internal/subscriptions?status=ACTIVE
   ```

4. **Aplicar override de capability a organización**
   ```
   POST /api/v1/internal/organizations/{org_id}/capability-overrides
   ```

---

## Diagrama de Entidades

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  ┌─────────────┐         ┌─────────────────┐                       │
│  │   Plans     │◄────────│ Plan_Capabilities│                      │
│  └─────────────┘         └─────────────────┘                       │
│         │                                                           │
│         │ define                                                    │
│         ▼                                                           │
│  ┌─────────────┐    tiene    ┌─────────────────────┐               │
│  │Subscriptions│◄────────────│    Organizations    │               │
│  └─────────────┘   muchas    │    (tabla clients)  │               │
│                              └─────────────────────┘               │
│                                       │                             │
│                    ┌──────────────────┼──────────────────┐         │
│                    │                  │                  │         │
│                    ▼                  ▼                  ▼         │
│            ┌─────────────┐   ┌─────────────┐   ┌─────────────────┐ │
│            │    Users    │   │   Devices   │   │ Org_Capabilities│ │
│            └─────────────┘   └─────────────┘   │   (overrides)   │ │
│                    │                           └─────────────────┘ │
│                    │                                               │
│                    ▼                                               │
│         ┌───────────────────┐                                      │
│         │ Organization_Users │                                     │
│         │   (roles: owner,   │                                     │
│         │    admin, billing, │                                     │
│         │    member)         │                                     │
│         └───────────────────┘                                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Flujos de Negocio Actualizados

### Flujo 1: Registro de Nueva Organización

```
1. POST /api/v1/auth/register
   ├── Crear Account + Organization (status=ACTIVE)
   ├── Crear User (email_verified=false)
   ├── Crear Organization_User (role=owner)
   ├── Asignar capabilities del plan FREE/TRIAL
   └── Enviar email de verificación

2. Usuario verifica email
   └── Organization.status = ACTIVE

3. Organización puede comenzar a operar
```

### Flujo 2: Consultar Información de Organización

```
GET /api/v1/accounts/organization

Respuesta:
{
  "organization": {
    "id": "...",
    "name": "...",
    "status": "ACTIVE"
  },
  "subscriptions": {
    "active": [...],
    "history": [...]
  },
  "effective_capabilities": {
    "max_devices": 100,
    "max_geofences": 50,
    ...
  },
  "current_user_role": "owner"
}
```

### Flujo 3: Validación de Acceso por Capability

```
Usuario intenta crear geocerca #51

1. Obtener organization_id del token
2. Calcular capabilities efectivas:
   - plan.max_geofences = 50
   - org_override.max_geofences = null
   - efectivo = 50
3. Contar geocercas actuales = 50
4. 50 >= 50 → RECHAZADO

Respuesta 403:
{
  "detail": "Has alcanzado el límite de geocercas de tu plan",
  "current": 50,
  "limit": 50,
  "upgrade_available": true
}
```

---

## Consideraciones de Implementación

### 1. Campo `active_subscription_id` (Deprecado)

El campo `active_subscription_id` en la tabla `clients` existe por compatibilidad pero NO debe usarse como fuente de verdad. 

**Enfoque correcto:**
- Calcular suscripciones activas dinámicamente
- Usar el módulo `app/services/subscription_query.py` como ÚNICA fuente de verdad

### Regla Única de Suscripción Activa

```
Una suscripción se considera ACTIVA si cumple TODAS las condiciones:
┌─────────────────────────────────────────────────────────────┐
│  1. status IN ('ACTIVE', 'TRIAL')                           │
│  2. expires_at > now() OR expires_at IS NULL                │
└─────────────────────────────────────────────────────────────┘

Si hay MÚLTIPLES suscripciones activas:
- Para capabilities: se usa la más reciente por started_at
- Para listados: se muestran todas ordenadas por started_at DESC
```

**Módulo centralizado:** `app/services/subscription_query.py`

```python
# USO CORRECTO - Funciones centralizadas
from app.services.subscription_query import (
    get_active_subscriptions,       # Lista todas las activas
    get_primary_active_subscription, # La principal (más reciente)
    get_active_plan_id,             # Plan de la suscripción principal
    has_active_subscription,        # ¿Tiene al menos una activa?
)

# USO INCORRECTO - NO hacer esto
client.active_subscription_id  # DEPRECADO
```

### 2. Campo `is_master` (Legacy)

El campo `is_master` se mantiene por compatibilidad pero debe complementarse con la tabla `organization_users` para roles explícitos.

**Mapeo temporal:**
- `is_master = true` → owner o admin
- `is_master = false` → member

### Resolución de Roles Centralizada

**Módulo centralizado:** `app/services/organization.py`

```python
# USO CORRECTO - OrganizationService como única fuente de verdad
from app.services.organization import OrganizationService

role = OrganizationService.get_user_role(db, user_id, client_id)
# Internamente maneja el fallback a is_master

# USO INCORRECTO - NO hacer consultas manuales duplicadas
membership = db.query(OrganizationUser).filter(...).first()
if not membership and user.is_master:  # ← NO duplicar esta lógica
    role = "owner"
```

### Creación de Membership

Cuando se crea una nueva organización, el usuario creador se registra automáticamente en `organization_users` con rol `owner`:

```python
# En POST /api/v1/auth/register se ejecuta:
1. Crear Account + Organization
2. Crear User (is_master=True para compatibilidad)
3. Crear OrganizationUser (role=owner)  # ← FUENTE DE VERDAD
```

### 3. Resolución de Capabilities

**Módulo centralizado:** `app/services/capabilities.py`

La resolución de capabilities se hace en un punto único para garantizar consistencia:

```python
# USO CORRECTO - CapabilityService como única fuente de verdad
from app.services.capabilities import CapabilityService

# Obtener capability específica
max_devices = CapabilityService.get_limit(db, client_id, "max_devices")

# Verificar feature
has_ai = CapabilityService.has_capability(db, client_id, "ai_features")

# Validar antes de crear
if not CapabilityService.validate_limit(db, client_id, "max_geofences", current_count):
    raise HTTPException(403, "Límite alcanzado")
```

**Regla de resolución:**
```
effective_capability(org_id, capability_name) =
    1. organization_capabilities.get(org_id, capability_name) si no expirado
    ?? 2. plan_capabilities del plan de suscripción activa principal
    ?? 3. DEFAULT_CAPABILITIES del sistema
```

**Nota:** CapabilityService usa `subscription_query.get_active_plan_id()` internamente, garantizando que la misma regla de "suscripción activa" se aplique en todo el sistema.

---

## Glosario

| Término | Definición |
|---------|------------|
| **Organización** | Entidad de negocio que contrata servicios (tabla `clients`) |
| **Suscripción** | Contrato de servicio con un plan específico |
| **Plan** | Conjunto de características y precios |
| **Capability** | Límite o feature que determina acceso |
| **Override** | Valor de capability específico para una organización |
| **Rol** | Nivel de permisos de un usuario en la organización |
| **Owner** | Usuario propietario de la organización |
| **API Interna** | Endpoints administrativos con autenticación PASETO |

---

**Última actualización**: Diciembre 2025  
**Versión**: 2.1.0 - Centralización de lógica de suscripciones, roles y capabilities


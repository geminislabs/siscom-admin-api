# Arquitectura del Sistema

## Descripción General

SISCOM Admin API es una aplicación FastAPI que implementa un sistema **SaaS B2B multi-tenant** para gestión de dispositivos GPS/IoT.

> **Referencia Clave**: Ver [Modelo Organizacional](organizational-model.md) para entender la semántica de negocio.

---

## Stack Tecnológico

### Backend

| Tecnología | Versión | Propósito |
|------------|---------|-----------|
| **FastAPI** | 0.109+ | Framework web de alto rendimiento |
| **Python** | 3.12+ | Lenguaje de programación |
| **SQLAlchemy 2.x** | 2.0+ | ORM para base de datos |
| **SQLModel** | Latest | Modelos híbridos Pydantic+SQLAlchemy |
| **Pydantic** | 2.0+ | Validación de datos |

### Base de Datos

| Tecnología | Versión | Propósito |
|------------|---------|-----------|
| **PostgreSQL** | 16 | Base de datos relacional |
| **Alembic** | Latest | Migraciones de esquema |

### Autenticación

| Tecnología | Propósito |
|------------|-----------|
| **AWS Cognito** | Gestión de identidad (usuarios externos) |
| **JWT** | Tokens de autenticación |
| **PASETO** | Tokens para servicios internos |
| **Boto3** | SDK de AWS para Python |

### DevOps

| Tecnología | Propósito |
|------------|-----------|
| **Docker** | Contenedorización |
| **Docker Compose** | Orquestación local |
| **GitHub Actions** | CI/CD |

---

## Arquitectura Multi-tenant

### Concepto de Organización

En este sistema, una **Organización** (tabla `clients`) representa una entidad de negocio que contrata servicios. Cada organización tiene sus datos completamente aislados.

```
┌─────────────────────────────────────────────────────────────────┐
│                    ARQUITECTURA MULTI-TENANT                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Token JWT                                                     │
│       ↓                                                         │
│   Extraer cognito_sub                                           │
│       ↓                                                         │
│   Buscar Usuario por cognito_sub                                │
│       ↓                                                         │
│   Obtener organization_id (client_id)                           │
│       ↓                                                         │
│   TODAS las consultas filtradas por organization_id             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Aislamiento de Datos

| Garantía | Descripción |
|----------|-------------|
| **Seguridad** | Imposible acceder a datos de otras organizaciones |
| **Simplicidad** | Una sola base de datos para todos |
| **Escalabilidad** | Fácil agregar nuevas organizaciones |
| **Mantenimiento** | Un solo código base |

---

## Modelo de Datos

### Diagrama de Entidades Principal

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
│  │Subscriptions│◄────────────│   Organizations     │               │
│  └─────────────┘   MÚLTIPLES │   (tabla clients)   │               │
│                              └─────────────────────┘               │
│                                       │                             │
│                    ┌──────────────────┼──────────────────┐         │
│                    │                  │                  │         │
│                    ▼                  ▼                  ▼         │
│            ┌─────────────┐   ┌─────────────┐   ┌─────────────────┐ │
│            │    Users    │   │   Devices   │   │ Org_Capabilities│ │
│            └─────────────┘   └─────────────┘   │   (overrides)   │ │
│                    │                │          └─────────────────┘ │
│                    │                │                               │
│                    ▼                ▼                               │
│         ┌───────────────┐  ┌───────────────┐                       │
│         │Org_Users      │  │Device_Services│                       │
│         │(roles)        │  │(suscripciones)│                       │
│         └───────────────┘  └───────────────┘                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Entidades Principales

```
Organization (clients)
├── Users (usuarios de la organización)
│   └── Organization_Users (roles: owner, admin, billing, member)
├── Subscriptions (MÚLTIPLES suscripciones)
├── Devices (dispositivos GPS)
│   └── DeviceServices (servicios por dispositivo)
├── Units (vehículos/activos)
├── Orders (órdenes de compra)
├── Payments (historial de pagos)
└── Capability_Overrides (ajustes específicos)
```

### Relaciones Clave

```
Organization 1:N Users
Organization 1:N Subscriptions      ← MÚLTIPLES suscripciones
Organization 1:N Devices
Organization 1:N Units
Organization 1:N Orders
Organization 1:N Payments
Organization 1:N Capability_Overrides

User N:1 Organization
User 1:1 Organization_User (rol)

Subscription N:1 Organization
Subscription N:1 Plan

Device N:1 Organization
Device 1:N DeviceServices
DeviceService N:1 Plan
DeviceService 1:1 Payment

Plan 1:N Plan_Capabilities
```

---

## Sistema de Autenticación Dual

### 1. Autenticación de Usuarios (Cognito)

Para usuarios finales que acceden a través de aplicaciones cliente:

```
┌─────────────────────────────────────────────────────────────────┐
│                   FLUJO COGNITO (Usuarios)                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Cliente                        API                  Cognito   │
│      │                            │                      │      │
│      │─── POST /auth/login ──────►│                      │      │
│      │    {email, password}       │── Validate ─────────►│      │
│      │                            │                      │      │
│      │                            │◄── Tokens ───────────│      │
│      │◄── {access, id, refresh} ──│                      │      │
│      │                            │                      │      │
│      │─── GET /devices/ ─────────►│                      │      │
│      │    Auth: Bearer <token>    │── Verify Token ─────►│      │
│      │                            │                      │      │
│      │                            │◄── Valid + sub ──────│      │
│      │                            │                      │      │
│      │                            │── Query(client_id) ──►│ DB  │
│      │◄── [devices] ──────────────│                      │      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2. Autenticación de Servicios (PASETO)

Para operaciones administrativas internas (API interna):

```
┌─────────────────────────────────────────────────────────────────┐
│                   FLUJO PASETO (Servicios)                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   gac-web                        API                            │
│      │                            │                             │
│      │─── POST /auth/internal ───►│                             │
│      │    {service, role}         │── Generate PASETO ──►       │
│      │                            │                             │
│      │◄── {token} ────────────────│                             │
│      │                            │                             │
│      │─── GET /internal/organizations ─►│                             │
│      │    Auth: Bearer <paseto>   │── Verify PASETO ───►        │
│      │                            │                             │
│      │                            │── Query ALL orgs ───► DB    │
│      │◄── [all_organizations] ────│                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Flujo de Autenticación

### 1. Registro de Organización

```
POST /api/v1/auth/register
  ↓
Crear Organization (status=PENDING)
  ↓
Crear User (is_master=true, email_verified=false)
  ↓
Crear Organization_User (role=owner)
  ↓
Generar token de verificación con password_temp
  ↓
Enviar email de verificación
```

### 2. Verificación de Email

```
Usuario hace clic en link del email
  ↓
POST /api/v1/auth/verify-email?token=...
  ↓
Validar token (no expirado, no usado)
  ↓
Crear usuario en AWS Cognito
  ↓
Establecer contraseña usando password_temp
  ↓
Actualizar User.cognito_sub
  ↓
Actualizar Organization.status = ACTIVE
  ↓
Eliminar password_temp permanentemente
```

### 3. Login

```
POST /api/v1/auth/login
  ↓
Validar credenciales en Cognito
  ↓
Obtener tokens (access, id, refresh)
  ↓
Actualizar User.last_login_at
  ↓
Retornar tokens al cliente
```

### 4. Request Autenticado

```
Request con Authorization: Bearer <token>
  ↓
Validar token con Cognito (o PASETO si es interno)
  ↓
Extraer cognito_sub del token
  ↓
Buscar usuario por cognito_sub
  ↓
Extraer organization_id (client_id) del usuario
  ↓
Ejecutar query con filtro por organization_id
```

---

## Sistema de Suscripciones

### Principio: Múltiples Suscripciones

> Una organización puede tener **MÚLTIPLES suscripciones** simultáneamente o a lo largo del tiempo.

```
┌─────────────────────────────────────────────────────────────────┐
│                   SUSCRIPCIONES MÚLTIPLES                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Organization "Transportes XYZ"                                │
│       │                                                         │
│       ├── Subscription 1 (EXPIRED, Plan Básico, 2023)          │
│       ├── Subscription 2 (CANCELLED, Plan Pro, Q1 2024)        │
│       ├── Subscription 3 (ACTIVE, Plan Enterprise, actual)     │
│       └── Subscription 4 (TRIAL, Plan Premium, evaluación)     │
│                                                                 │
│   ⚠️  active_subscription_id es DEPRECADO                       │
│       Las suscripciones activas se calculan dinámicamente       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Estados de Suscripción

| Estado | Descripción |
|--------|-------------|
| `ACTIVE` | Suscripción vigente y operativa |
| `TRIAL` | Período de prueba |
| `EXPIRED` | Vencida por tiempo |
| `CANCELLED` | Cancelada manualmente |

---

## Sistema de Capabilities

### Resolución de Capabilities

```
┌─────────────────────────────────────────────────────────────────┐
│                   RESOLUCIÓN DE CAPABILITIES                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   effective_capability(org_id, capability_name) =               │
│                                                                 │
│       organization_capability_override                          │
│               ??                                                │
│       plan_capability (del plan activo)                         │
│               ??                                                │
│       default_capability                                        │
│                                                                 │
│   Ejemplo:                                                      │
│   Plan: max_geofences = 50                                      │
│   Override: max_geofences = 100                                 │
│   Efectivo: 100 (override gana)                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Uso en Validaciones

```python
# Antes de crear geocerca
effective = get_effective_capability(org_id, "max_geofences")
current = count_geofences(org_id)

if current >= effective:
    raise HTTPException(
        status_code=403,
        detail="Has alcanzado el límite de geocercas de tu plan"
    )
```

---

## Roles Organizacionales

### Jerarquía

```
┌──────────┐  Permisos totales
│  OWNER   │  Único por organización
└────┬─────┘
     │
┌────┴─────┐  Gestión de usuarios y config
│  ADMIN   │  Puede invitar usuarios
└────┬─────┘
     │
┌────┴─────┐  Gestión de pagos
│ BILLING  │  Ve suscripciones y pagos
└────┬─────┘
     │
┌────┴─────┐  Acceso operativo
│  MEMBER  │  Permisos según asignaciones
└──────────┘
```

### Mapeo Legacy

| `is_master` | Rol Equivalente |
|-------------|-----------------|
| `true` (primer usuario) | `owner` |
| `true` (invitado) | `admin` |
| `false` | `member` |

---

## Flujo de Negocio

### Compra de Hardware

```
1. Cliente crea orden
   POST /api/v1/orders/
   ↓
2. Sistema crea Payment (PENDING)
   ↓
3. Cliente realiza pago externo
   ↓
4. Admin confirma pago
   UPDATE payment.status = SUCCESS
   ↓
5. Admin envía dispositivos
   ↓
6. Admin marca orden como completada
   UPDATE order.status = COMPLETED
```

### Activación de Servicio

```
1. Cliente registra dispositivo
   POST /api/v1/devices/
   ↓
2. Cliente instala físicamente el dispositivo
   ↓
3. Cliente selecciona plan
   GET /api/v1/plans/
   ↓
4. Cliente activa servicio
   POST /api/v1/services/activate
   ↓
5. Sistema valida capabilities
   ↓
6. Sistema crea Payment (SUCCESS)
   ↓
7. Sistema crea Subscription
   ↓
8. Sistema crea DeviceService (ACTIVE)
   ↓
9. Sistema actualiza Device.active = true
   ↓
10. Dispositivo comienza a rastrear
```

---

## Capas de la Aplicación

### 1. API Layer (app/api/)

Responsabilidades:
- Definir endpoints HTTP
- Validar request/response
- Manejar autenticación/autorización
- Retornar respuestas HTTP

```python
@router.post("/activate")
def activate_service(
    service_in: DeviceServiceCreate,
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
):
    return activate_device_service(db, organization_id, ...)
```

### 2. Service Layer (app/services/)

Responsabilidades:
- Implementar lógica de negocio
- Coordinar múltiples operaciones
- Validar capabilities y límites
- Manejar transacciones

```python
def activate_device_service(
    db: Session,
    organization_id: UUID,
    device_id: UUID,
    plan_id: UUID
):
    # Validar device ownership
    # Verificar capabilities
    # Verificar no hay servicio activo
    # Crear subscription
    # Crear payment
    # Crear device_service
    # Actualizar device.active
    return device_service
```

### 3. Model Layer (app/models/)

Responsabilidades:
- Definir estructura de datos
- Relaciones entre tablas
- Validaciones de DB

```python
class Organization(SQLModel, table=True):
    __tablename__ = "clients"

    id: UUID
    name: str
    status: OrganizationStatus
    # active_subscription_id: DEPRECADO
    created_at: datetime
    updated_at: datetime
```

### 4. Schema Layer (app/schemas/)

Responsabilidades:
- Definir contratos de API
- Validar entrada/salida
- Transformar datos

```python
class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    status: str
    subscriptions: SubscriptionsResponse
    effective_capabilities: dict
```

---

## Seguridad

### Autenticación

| Método | Caso de Uso |
|--------|-------------|
| **AWS Cognito** | Usuarios finales |
| **PASETO** | Servicios internos |

### Autorización

| Nivel | Implementación |
|-------|----------------|
| **Multi-tenant** | Filtro automático por organization_id |
| **Role-based** | Validación de rol en endpoints |
| **Resource-based** | Verificar ownership de recursos |
| **Capability-based** | Validar límites antes de operaciones |

### Mejores Prácticas

```python
# ✅ CORRECTO: Filtrar por organization_id
devices = db.query(Device).filter(
    Device.client_id == organization_id
).all()

# ❌ INCORRECTO: No filtrar por organization_id
devices = db.query(Device).all()

# ✅ CORRECTO: Validar capabilities
if current_count >= effective_limit:
    raise HTTPException(403, "Límite alcanzado")

# ✅ CORRECTO: Validar rol
if user.role not in ["owner", "admin"]:
    raise HTTPException(403, "Permisos insuficientes")
```

---

## Escalabilidad

### Horizontal

- **Stateless**: No estado en servidor
- **Load Balancer**: Múltiples instancias de API
- **Session en JWT**: No requiere sesiones en servidor

### Vertical

- **Connection Pooling**: SQLAlchemy pool
- **Async where needed**: FastAPI async endpoints
- **Índices DB**: Optimizar queries frecuentes

### Caching

```python
# Capabilities (pueden cachearse por sesión)
@lru_cache(maxsize=1000)
def get_effective_capabilities(organization_id: UUID):
    # Resolver capabilities
    return capabilities

# Planes (cambian raramente)
@lru_cache(maxsize=100)
def get_active_plans(db: Session):
    return db.query(Plan).filter(Plan.active == True).all()
```

---

## Monitoreo

### Logs

- **Request/Response**: FastAPI logging
- **Errores de negocio**: Application logs
- **Queries lentas**: Database logs
- **Auditoría**: Operaciones sensibles (cambios de rol, etc.)

### Métricas

- Requests por segundo
- Latencia promedio
- Error rate
- Organizaciones activas
- Dispositivos activos
- Suscripciones por estado

### Alertas

- Error rate > 5%
- Latency > 1s
- DB connections > 80%
- Cognito rate limits

---

## Testing

### Unit Tests

```python
def test_capability_resolution():
    # Given
    plan_cap = {"max_geofences": 50}
    org_override = {"max_geofences": 100}

    # When
    effective = resolve_capability("max_geofences", plan_cap, org_override)

    # Then
    assert effective == 100  # Override gana
```

### Integration Tests

```python
def test_activate_service_endpoint(client, auth_token):
    response = client.post(
        "/api/v1/services/activate",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={...}
    )
    assert response.status_code == 201
```

---

## Deployment

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0"]
```

### Producción

- **Nginx**: Reverse proxy
- **Gunicorn**: WSGI server con workers
- **PostgreSQL**: Instancia dedicada
- **SSL/TLS**: Certificados válidos
- **Backups**: Diarios automáticos
- **VPN/Firewall**: Proteger API interna

---

## Roadmap de Arquitectura

### Corto Plazo
- [ ] Implementar tabla organization_users con roles
- [ ] Implementar capability_overrides
- [ ] Calcular suscripciones activas dinámicamente
- [ ] Deprecar uso de active_subscription_id

### Mediano Plazo
- [ ] Endpoints de gestión de capabilities
- [ ] Dashboard de métricas por organización
- [ ] Webhooks de eventos

### Largo Plazo
- [ ] API pública para integraciones
- [ ] Multi-región
- [ ] Analytics avanzado

---

**Última actualización**: Diciembre 2025  
**Referencia**: [Modelo Organizacional](organizational-model.md)

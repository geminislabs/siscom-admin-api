"""
Router principal de la API v1.

Organiza todos los endpoints del sistema:
- API Pública (Cognito): /auth, /accounts, /organizations, /users, /subscriptions, etc.
- API Interna (PASETO): /internal/*

MODELO CONCEPTUAL:
==================
Account = Raíz comercial (billing, facturación)
Organization = Raíz operativa (permisos, uso diario)

SEPARACIÓN DE APIs:
===================
API Pública:
- Uso por frontend cliente
- Read-only para catálogos (planes, productos)
- No permite crear ni modificar catálogo

API Interna:
- Uso exclusivo GAC (staff)
- Control total del catálogo
- Operaciones compuestas (crear/editar plan con capabilities y productos)

ENDPOINTS PRINCIPALES:
======================
- POST /auth/register: Registro (crea Account + Organization + User)
- GET /auth/me: Mi Account
- POST /organizations: Crear nueva organización
- GET /organizations: Listar organizaciones del Account
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    accounts,
    alert_rules,
    alerts,
    auth,
    billing,
    capabilities,
    commands,
    contact,
    device_events,
    devices,
    geofences,
    orders,
    organization_capabilities,
    organization_users,
    organizations,
    payments,
    plans,
    services,
    subscriptions,
    telemetry,
    trips,
    unit_devices,
    units,
    user_devices,
    user_units,
    users,
)
from app.api.v1.endpoints.internal import accounts as internal_accounts
from app.api.v1.endpoints.internal import organizations as internal_organizations
from app.api.v1.endpoints.internal import plans as internal_plans
from app.api.v1.endpoints.internal import products as internal_products

api_router = APIRouter()

# ============================================
# API Pública (Autenticación: Cognito)
# ============================================

# Autenticación
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])

# Accounts (raíz comercial - onboarding + perfil progresivo)
api_router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])

# Organizations (raíz operativa - múltiples por account)
api_router.include_router(
    organizations.router, prefix="/organizations", tags=["organizations"]
)

# Organization Users (gestión de usuarios de una organización)
api_router.include_router(
    organization_users.router,
    prefix="/organizations",
    tags=["organization-users"],
)

# Organization Capabilities (overrides de capabilities por organización)
api_router.include_router(
    organization_capabilities.router,
    prefix="/organizations",
    tags=["organization-capabilities"],
)

# Usuarios
api_router.include_router(users.router, prefix="/users", tags=["users"])

# Suscripciones (múltiples por organización)
api_router.include_router(
    subscriptions.router, prefix="/subscriptions", tags=["subscriptions"]
)

# Capabilities (límites y features)
api_router.include_router(
    capabilities.router, prefix="/capabilities", tags=["capabilities"]
)

# Planes
api_router.include_router(plans.router, prefix="/plans", tags=["plans"])

# Dispositivos y Unidades
api_router.include_router(devices.router, prefix="/devices", tags=["devices"])

# Telemetría agregada (GET /devices/{device_id}/telemetry y POST /telemetry/query)
api_router.include_router(telemetry.router, tags=["telemetry"])
api_router.include_router(units.router, prefix="/units", tags=["units"])
api_router.include_router(
    unit_devices.router, prefix="/unit-devices", tags=["unit-devices"]
)
api_router.include_router(
    user_devices.router, prefix="/user-devices", tags=["user-devices"]
)
api_router.include_router(user_units.router, prefix="/user-units", tags=["user-units"])
api_router.include_router(
    device_events.router, prefix="/device-events", tags=["device-events"]
)

# Servicios (legacy, considerar usar subscriptions)
api_router.include_router(services.router, prefix="/services", tags=["services"])

# Billing y Pagos (read-only)
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])

# Viajes
api_router.include_router(trips.router, prefix="/trips", tags=["trips"])

# Reglas de alertas y alertas generadas
api_router.include_router(
    alert_rules.router,
    prefix="/alert_rules",
    tags=["alert-rules"],
)
api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])

# Geocercas
api_router.include_router(geofences.router, prefix="/geofences", tags=["geofences"])

# Comandos
api_router.include_router(commands.router, prefix="/commands", tags=["commands"])

# Contacto
api_router.include_router(contact.router, prefix="/contact", tags=["contact"])

# ============================================
# API Interna (Autenticación: PASETO)
# ============================================

api_router.include_router(
    internal_accounts.router, prefix="/internal/accounts", tags=["internal-accounts"]
)
api_router.include_router(
    internal_organizations.router,
    prefix="/internal/organizations",
    tags=["internal-organizations"],
)

# Internal Plans (Gestión de planes, productos y capabilities)
api_router.include_router(
    internal_plans.router,
    prefix="/internal/plans",
    tags=["internal-plans"],
)

# Internal Products (Gestión de productos)
api_router.include_router(
    internal_products.router,
    prefix="/internal/products",
    tags=["internal-products"],
)

"""
Schemas de la aplicación.

Este módulo exporta todos los schemas Pydantic utilizados en siscom-admin-api.

MODELO CONCEPTUAL:
==================
Account = Raíz comercial (billing, facturación) - SIEMPRE existe
Organization = Raíz operativa (permisos, uso diario) - SIEMPRE pertenece a Account

ONBOARDING:
===========
POST /clients usa OnboardingRequest/OnboardingResponse
PATCH /accounts/{id} usa AccountUpdate/AccountUpdateResponse

REGLA DE ORO:
=============
Los nombres NO son identidad. Los UUID sí.
"""

# Account
from app.schemas.account import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
    AccountUpdateResponse,
    AccountWithOrganizationsOut,
)
from app.schemas.alert import AlertOut
from app.schemas.alert_rule import (
    AlertRuleCreate,
    AlertRuleDeleteOut,
    AlertRuleOut,
    AlertRuleUnitsAssign,
    AlertRuleUnitsOut,
    AlertRuleUnitsUnassign,
    AlertRuleUpdate,
)

# Capabilities
from app.schemas.capability import (
    CapabilitiesSummaryOut,
    CapabilityOut,
    OrganizationCapabilityCreate,
    OrganizationCapabilityOut,
    ResolvedCapabilityOut,
    ValidateLimitRequest,
    ValidateLimitResponse,
)

# Onboarding (POST /clients)
from app.schemas.client import (
    ClientBase,
    ClientOut,
    OnboardingRequest,
    OnboardingResponse,
)

# Commands
from app.schemas.command import (
    CommandCreate,
    CommandListResponse,
    CommandOut,
    CommandResponse,
)

# Devices
from app.schemas.device import (
    DeviceBase,
    DeviceCreate,
    DeviceOut,
    UnitBase,
    UnitCreate,
    UnitOut,
)

# Device Services
from app.schemas.device_service import (
    DeviceServiceConfirmPayment,
    DeviceServiceCreate,
    DeviceServiceOut,
    DeviceServiceWithDetails,
)

# Orders
from app.schemas.order import OrderCreate, OrderItemCreate, OrderItemOut, OrderOut

# Organization
from app.schemas.organization import (
    InviteUserRequest,
    OrganizationMemberOut,
    OrganizationMembersListOut,
    OrganizationOut,
    OrganizationSummaryOut,
    OrganizationUpdate,
    SubscriptionsListOut,
    SubscriptionSummaryOut,
    UpdateMemberRoleRequest,
)

# Payments
from app.schemas.payment import PaymentBase, PaymentCreate, PaymentOut

# Plans
from app.schemas.plan import PlanBase, PlanOut, PlansListOut, PlanWithCapabilitiesOut

# Subscriptions
from app.schemas.subscription import (
    SubscriptionCancelRequest,
    SubscriptionCreate,
    SubscriptionOut,
    SubscriptionRenewRequest,
    SubscriptionWithPlanOut,
)

# Trips
from app.schemas.trip import (
    TripAlertOut,
    TripBase,
    TripDetail,
    TripEventOut,
    TripListResponse,
    TripOut,
    TripPointOut,
)

# Users
from app.schemas.user import UserBase, UserCreate, UserOut
from app.schemas.user_device import (
    DeviceDeactivateIn,
    DeviceDeactivateOut,
    DeviceRegisterIn,
    DeviceRegisterOut,
)

__all__ = [
    # Account
    "AccountCreate",
    "AccountOut",
    "AccountUpdate",
    "AccountUpdateResponse",
    "AccountWithOrganizationsOut",
    "AlertOut",
    "AlertRuleCreate",
    "AlertRuleUpdate",
    "AlertRuleOut",
    "AlertRuleDeleteOut",
    "AlertRuleUnitsAssign",
    "AlertRuleUnitsUnassign",
    "AlertRuleUnitsOut",
    # Capabilities
    "CapabilityOut",
    "ResolvedCapabilityOut",
    "CapabilitiesSummaryOut",
    "OrganizationCapabilityCreate",
    "OrganizationCapabilityOut",
    "ValidateLimitRequest",
    "ValidateLimitResponse",
    # Onboarding
    "OnboardingRequest",
    "OnboardingResponse",
    # Client/Organization (legacy compatibility)
    "ClientBase",
    "ClientOut",
    # Organization
    "OrganizationOut",
    "OrganizationUpdate",
    "OrganizationSummaryOut",
    "OrganizationMemberOut",
    "OrganizationMembersListOut",
    "InviteUserRequest",
    "UpdateMemberRoleRequest",
    "SubscriptionSummaryOut",
    "SubscriptionsListOut",
    # Commands
    "CommandCreate",
    "CommandResponse",
    "CommandOut",
    "CommandListResponse",
    # Users
    "UserBase",
    "UserCreate",
    "UserOut",
    "DeviceRegisterIn",
    "DeviceRegisterOut",
    "DeviceDeactivateIn",
    "DeviceDeactivateOut",
    # Devices
    "DeviceBase",
    "DeviceCreate",
    "DeviceOut",
    "UnitBase",
    "UnitCreate",
    "UnitOut",
    # Plans
    "PlanBase",
    "PlanOut",
    "PlanWithCapabilitiesOut",
    "PlansListOut",
    # Subscriptions
    "SubscriptionCreate",
    "SubscriptionOut",
    "SubscriptionWithPlanOut",
    "SubscriptionCancelRequest",
    "SubscriptionRenewRequest",
    # Device Services
    "DeviceServiceCreate",
    "DeviceServiceOut",
    "DeviceServiceConfirmPayment",
    "DeviceServiceWithDetails",
    # Payments
    "PaymentBase",
    "PaymentCreate",
    "PaymentOut",
    # Orders
    "OrderCreate",
    "OrderOut",
    "OrderItemCreate",
    "OrderItemOut",
    # Trips
    "TripBase",
    "TripOut",
    "TripDetail",
    "TripPointOut",
    "TripAlertOut",
    "TripEventOut",
    "TripListResponse",
]

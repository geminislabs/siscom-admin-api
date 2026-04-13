"""
Modelos de la aplicación.

Este módulo exporta todos los modelos SQLModel utilizados en siscom-admin-api.

MODELO CONCEPTUAL:
==================
Account = Raíz comercial (billing, facturación) - SIEMPRE existe
Organization = Raíz operativa (permisos, uso diario) - SIEMPRE pertenece a Account

Relación: Account 1 ──< Organization *

En el onboarding rápido (POST /clients):
1. Se crea Account (name = account_name del input)
2. Se crea Organization default (pertenece a Account)
3. Se crea User master (owner de Organization)
4. Se registra en Cognito

REGLA DE ORO:
=============
Los nombres NO son identidad. Los UUID sí.
Los nombres pueden repetirse; la unicidad está en los UUIDs.
"""

# Account (raíz comercial)
from app.models.account import Account, AccountStatus

# Account Events (auditoría)
from app.models.account_event import (
    AccountEvent,
    ActorType,
    EventType,
    TargetType,
)

# Account Users (roles a nivel account)
from app.models.account_user import AccountRole, AccountUser
from app.models.alert import Alert
from app.models.alert_rule import AlertRule, AlertRuleUnit

# Capabilities
from app.models.capability import (
    Capability,
    CapabilityValueType,
    OrganizationCapability,
    PlanCapability,
)

# Commands
from app.models.command import Command
from app.models.device import Device, DeviceEvent

# Device Services (LEGACY - no usar en código nuevo)
from app.models.device_service import (
    DeviceService,
    DeviceServiceStatus,
    SubscriptionType,
)
from app.models.geofence import Geofence, GeofenceCell
from app.models.invitation import Invitation
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem, OrderItemType

# Organization (raíz operativa, antes "Client")
from app.models.organization import Organization, OrganizationStatus

# Organization Users (roles)
from app.models.organization_user import OrganizationRole, OrganizationUser

# Payments & Orders
from app.models.payment import Payment, PaymentStatus

# Subscriptions & Plans
from app.models.plan import Plan

# Products
from app.models.product import PlanProduct, Product

# SIM Cards
from app.models.sim_card import SimCard
from app.models.sim_kore_profile import SimKoreProfile
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus

# Tokens
from app.models.token_confirmacion import TokenConfirmacion, TokenType

# Trips
from app.models.trip import Trip, TripAlert, TripEvent, TripPoint
from app.models.unified_sim_profile import UnifiedSimProfile

# Units & Devices
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.models.unit_profile import UnitProfile

# Users
from app.models.user import User
from app.models.user_device import UserDevice
from app.models.user_unit import UserUnit
from app.models.vehicle_profile import VehicleProfile

__all__ = [
    # Account (raíz comercial)
    "Account",
    "AccountStatus",
    "AccountEvent",
    "ActorType",
    "EventType",
    "TargetType",
    "AccountUser",
    "AccountRole",
    "Alert",
    "AlertRule",
    "AlertRuleUnit",
    # Organization (raíz operativa)
    "Organization",
    "OrganizationStatus",
    "OrganizationUser",
    "OrganizationRole",
    # Capabilities
    "Capability",
    "CapabilityValueType",
    "PlanCapability",
    "OrganizationCapability",
    # Users
    "User",
    "Invitation",
    # Subscriptions & Plans
    "Plan",
    "Product",
    "PlanProduct",
    "Subscription",
    "SubscriptionStatus",
    "BillingCycle",
    # Commands
    "Command",
    # Units & Devices
    "Unit",
    "UnitProfile",
    "VehicleProfile",
    "Device",
    "DeviceEvent",
    "UnitDevice",
    "UserDevice",
    "UserUnit",
    # Payments & Orders
    "Payment",
    "PaymentStatus",
    "Order",
    "OrderStatus",
    "OrderItem",
    "OrderItemType",
    # Device Services (LEGACY)
    "DeviceService",
    "DeviceServiceStatus",
    "SubscriptionType",
    "Geofence",
    "GeofenceCell",
    # Tokens
    "TokenConfirmacion",
    "TokenType",
    # Trips
    "Trip",
    "TripPoint",
    "TripAlert",
    "TripEvent",
    # SIM Cards
    "SimCard",
    "SimKoreProfile",
    "UnifiedSimProfile",
]

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.device_service import (
    DeviceService,
    DeviceServiceStatus,
    SubscriptionType,
)
from app.models.payment import Payment, PaymentStatus
from app.models.plan import Plan
from app.utils.datetime import calculate_expiration, utcnow


def activate_device_service(
    db: Session,
    client_id: UUID,
    device_id: UUID,
    plan_id: UUID,
    subscription_type: str,
    simulate_immediate_payment: bool = True,
) -> DeviceService:
    """
    Activa un servicio para un dispositivo.

    1. Valida que el dispositivo pertenezca al cliente
    2. Verifica que no exista otro servicio ACTIVE para ese dispositivo
    3. Calcula expires_at según subscription_type
    4. Crea Payment (PENDING o SUCCESS según simulación)
    5. Crea DeviceService con status ACTIVE
    6. Actualiza device.active = True

    Args:
        db: Sesión de base de datos
        client_id: ID del cliente propietario
        device_id: ID del dispositivo a activar
        plan_id: ID del plan a aplicar
        subscription_type: 'MONTHLY' o 'YEARLY'
        simulate_immediate_payment: Si True, marca pago como SUCCESS inmediatamente

    Returns:
        DeviceService creado

    Raises:
        HTTPException: Si validaciones fallan
    """
    # 1. Validar que el dispositivo pertenezca al cliente
    device = (
        db.query(Device)
        .filter(Device.id == device_id, Device.client_id == client_id)
        .first()
    )

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispositivo no encontrado o no pertenece al cliente",
        )

    # 2. Verificar que no exista otro servicio ACTIVE para ese dispositivo
    existing_active = (
        db.query(DeviceService)
        .filter(
            DeviceService.device_id == device_id,
            DeviceService.status == DeviceServiceStatus.ACTIVE.value,
        )
        .first()
    )

    if existing_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El dispositivo ya tiene un servicio activo",
        )

    # Verificar que el plan existe
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan no encontrado",
        )

    # 3. Calcular expires_at
    expires_at = calculate_expiration(subscription_type)

    # Determinar el monto según tipo de suscripción
    if subscription_type == SubscriptionType.MONTHLY.value:
        amount = Decimal(str(plan.price_monthly))
    elif subscription_type == SubscriptionType.YEARLY.value:
        amount = Decimal(str(plan.price_yearly))
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipo de suscripción inválido",
        )

    # 4. Crear Payment
    payment_status = (
        PaymentStatus.SUCCESS if simulate_immediate_payment else PaymentStatus.PENDING
    )
    paid_at = utcnow() if simulate_immediate_payment else None

    payment = Payment(
        client_id=client_id,
        amount=str(amount),
        currency="MXN",
        method="card" if simulate_immediate_payment else None,
        status=payment_status.value,
        paid_at=paid_at,
        transaction_ref=(
            f"txn_{device_id}_{utcnow().timestamp()}"
            if simulate_immediate_payment
            else None
        ),
    )
    db.add(payment)
    db.flush()  # Para obtener el payment.id

    # 5. Crear DeviceService
    device_service_status = (
        DeviceServiceStatus.ACTIVE
        if simulate_immediate_payment
        else DeviceServiceStatus.ACTIVE
    )

    device_service = DeviceService(
        device_id=device_id,
        client_id=client_id,
        plan_id=plan_id,
        subscription_type=subscription_type,
        status=device_service_status.value,
        activated_at=utcnow(),
        expires_at=expires_at,
        auto_renew=True,
        payment_id=payment.id,
    )
    db.add(device_service)

    # 6. Actualizar device.active = True
    device.active = True
    db.add(device)

    db.commit()
    db.refresh(device_service)
    db.refresh(payment)

    return device_service

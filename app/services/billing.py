from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.device_service import DeviceService, DeviceServiceStatus
from app.models.payment import Payment, PaymentStatus
from app.utils.datetime import utcnow


def confirm_payment(
    db: Session,
    payment_id: UUID,
    device_service_id: UUID,
) -> Payment:
    """
    Confirma un pago y activa el servicio asociado si estaba pendiente.

    Args:
        db: Sesión de base de datos
        payment_id: ID del pago a confirmar
        device_service_id: ID del servicio de dispositivo asociado

    Returns:
        Payment actualizado

    Raises:
        HTTPException: Si no se encuentra el pago o servicio
    """
    # Buscar el pago
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pago no encontrado",
        )

    # Buscar el servicio de dispositivo
    device_service = (
        db.query(DeviceService).filter(DeviceService.id == device_service_id).first()
    )
    if not device_service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servicio de dispositivo no encontrado",
        )

    # Verificar que el payment_id del servicio coincida
    if device_service.payment_id != payment_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El pago no corresponde al servicio especificado",
        )

    # Actualizar el pago a SUCCESS
    payment.status = PaymentStatus.SUCCESS.value
    payment.paid_at = utcnow()
    db.add(payment)

    # Si el servicio estaba en PENDING, activarlo
    # (En nuestro flujo actual ya se crea como ACTIVE, pero lo dejamos por si cambia)
    if device_service.status != DeviceServiceStatus.ACTIVE.value:
        device_service.status = DeviceServiceStatus.ACTIVE.value
        db.add(device_service)

    # Actualizar device.active = True
    device = (
        db.query(Device).filter(Device.device_id == device_service.device_id).first()
    )
    if device:
        device.active = True
        db.add(device)

    db.commit()
    db.refresh(payment)

    return payment


def check_expired_services(db: Session) -> int:
    """
    Marca como EXPIRED los servicios cuyo expires_at ya pasó y auto_renew es False.
    Esta función está diseñada para ejecutarse como un cron job.

    Args:
        db: Sesión de base de datos

    Returns:
        Cantidad de servicios marcados como expirados
    """
    now = utcnow()

    # Buscar servicios ACTIVE que ya expiraron y no tienen auto_renew
    expired_services = (
        db.query(DeviceService)
        .filter(
            DeviceService.status == DeviceServiceStatus.ACTIVE.value,
            DeviceService.expires_at <= now,
            not DeviceService.auto_renew,
        )
        .all()
    )

    count = 0
    for service in expired_services:
        service.status = DeviceServiceStatus.EXPIRED.value
        db.add(service)

        # Verificar si el dispositivo tiene otros servicios activos
        other_active = (
            db.query(DeviceService)
            .filter(
                DeviceService.device_id == service.device_id,
                DeviceService.status == DeviceServiceStatus.ACTIVE.value,
                DeviceService.id != service.id,
            )
            .first()
        )

        # Si no hay otros servicios activos, marcar device.active = False
        if not other_active:
            device = (
                db.query(Device).filter(Device.device_id == service.device_id).first()
            )
            if device:
                device.active = False
                db.add(device)

        count += 1

    if count > 0:
        db.commit()

    return count


def cancel_device_service(
    db: Session,
    device_service_id: UUID,
    client_id: UUID,
) -> DeviceService:
    """
    Cancela un servicio de dispositivo.

    Args:
        db: Sesión de base de datos
        device_service_id: ID del servicio a cancelar
        client_id: ID del cliente (para validar ownership)

    Returns:
        DeviceService cancelado

    Raises:
        HTTPException: Si no se encuentra o no pertenece al cliente
    """
    device_service = (
        db.query(DeviceService)
        .filter(
            DeviceService.id == device_service_id,
            DeviceService.client_id == client_id,
        )
        .first()
    )

    if not device_service:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servicio no encontrado o no pertenece al cliente",
        )

    # Marcar como cancelado
    device_service.status = DeviceServiceStatus.CANCELLED.value
    device_service.cancelled_at = utcnow()
    db.add(device_service)

    # Verificar si hay otros servicios activos para el mismo dispositivo
    other_active = (
        db.query(DeviceService)
        .filter(
            DeviceService.device_id == device_service.device_id,
            DeviceService.status == DeviceServiceStatus.ACTIVE.value,
            DeviceService.id != device_service_id,
        )
        .first()
    )

    # Si no hay otros servicios activos, marcar device.active = False
    if not other_active:
        device = (
            db.query(Device)
            .filter(Device.device_id == device_service.device_id)
            .first()
        )
        if device:
            device.active = False
            db.add(device)

    db.commit()
    db.refresh(device_service)

    return device_service

"""Servicio para operaciones de Mobility Devices."""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.mobility_device import MobilityDevice
from app.models.user import User
from app.models.user_device import UserDevice
from app.schemas.mobility_device import MobilityDeviceUpdateIn
from app.utils.datetime import utcnow


class MobilityDeviceService:
    @staticmethod
    def get_device_by_id(
        db: Session, device_id: UUID, user: User, allow_other_user: bool = False
    ) -> MobilityDevice:
        """
        Obtiene un dispositivo por ID.
        Por defecto valida que pertenezca al usuario autenticado.
        """
        device = db.query(MobilityDevice).filter(MobilityDevice.id == device_id).first()
        if not device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dispositivo no encontrado",
            )
        if not allow_other_user and device.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para acceder a este dispositivo",
            )
        return device

    @staticmethod
    def update_device(
        db: Session, device: MobilityDevice, payload: MobilityDeviceUpdateIn
    ) -> MobilityDevice:
        """Actualiza campos editables de un dispositivo."""
        if payload.device_name is not None:
            device.device_name = payload.device_name
        if payload.app_version is not None:
            device.app_version = payload.app_version
        if payload.os_version is not None:
            device.os_version = payload.os_version
        if payload.metadata is not None:
            device.mobility_metadata = payload.metadata
        if payload.notification_device_id is not None:
            MobilityDeviceService._validate_notification_device(
                db, payload.notification_device_id, device.user_id, device.id
            )
            device.notification_device_id = payload.notification_device_id

        device.updated_at = utcnow()
        db.add(device)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Error al actualizar dispositivo. Valida notification_device_id.",
            ) from exc
        db.refresh(device)
        return device

    @staticmethod
    def activate_device(db: Session, device: MobilityDevice) -> MobilityDevice:
        """Activa un dispositivo."""
        device.is_active = True
        device.updated_at = utcnow()
        db.add(device)
        db.commit()
        db.refresh(device)
        return device

    @staticmethod
    def deactivate_device(db: Session, device: MobilityDevice) -> MobilityDevice:
        """Desactiva un dispositivo."""
        device.is_active = False
        device.updated_at = utcnow()
        db.add(device)
        db.commit()
        db.refresh(device)
        return device

    @staticmethod
    def associate_notification_device(
        db: Session, device: MobilityDevice, notification_device_id: UUID
    ) -> MobilityDevice:
        """Asocia un dispositivo de notificaciones."""
        MobilityDeviceService._validate_notification_device(
            db, notification_device_id, device.user_id, device.id
        )
        device.notification_device_id = notification_device_id
        device.updated_at = utcnow()
        db.add(device)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="notification_device_id ya está en uso por otro dispositivo",
            ) from exc
        db.refresh(device)
        return device

    @staticmethod
    def dissociate_notification_device(
        db: Session, device: MobilityDevice
    ) -> MobilityDevice:
        """Desasocia un dispositivo de notificaciones."""
        device.notification_device_id = None
        device.updated_at = utcnow()
        db.add(device)
        db.commit()
        db.refresh(device)
        return device

    @staticmethod
    def _validate_notification_device(
        db: Session,
        notification_device_id: UUID,
        user_id: UUID,
        exclude_mobility_device_id: Optional[UUID] = None,
    ) -> None:
        """
        Valida que notification_device_id:
        1. Existe
        2. Pertenece al mismo usuario
        3. No está asociado a otro mobility device (excepto el actual)
        """
        notification_device = (
            db.query(UserDevice)
            .filter(
                UserDevice.id == notification_device_id,
                UserDevice.user_id == user_id,
            )
            .first()
        )
        if not notification_device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="notification_device_id no existe o no pertenece al usuario",
            )

        query = db.query(MobilityDevice).filter(
            MobilityDevice.notification_device_id == notification_device_id
        )
        if exclude_mobility_device_id:
            query = query.filter(MobilityDevice.id != exclude_mobility_device_id)

        existing_association = query.first()
        if existing_association:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="notification_device_id ya está asociado a otro dispositivo de movilidad",
            )

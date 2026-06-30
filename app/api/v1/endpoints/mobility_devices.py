from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full
from app.db.session import get_db
from app.models.mobility_device import MobilityDevice
from app.models.user import User
from app.models.user_device import UserDevice
from app.schemas.common import DataResponse
from app.schemas.mobility_device import (
    MobilityDeviceCreateIn,
    MobilityDeviceNotificationDeviceIn,
    MobilityDeviceOut,
    MobilityDeviceUpdateIn,
)
from app.services.mobility_device_service import MobilityDeviceService

router = APIRouter()


def _build_mobility_device_out(device: MobilityDevice) -> MobilityDeviceOut:
    return MobilityDeviceOut(
        id=device.id,
        user_id=device.user_id,
        device_type=device.device_type,
        platform=device.platform,
        device_name=device.device_name,
        external_device_id=device.external_device_id,
        app_version=device.app_version,
        os_version=device.os_version,
        last_seen_at=device.last_seen_at,
        is_active=device.is_active,
        metadata=device.mobility_metadata,
        created_at=device.created_at,
        updated_at=device.updated_at,
        notification_device_id=device.notification_device_id,
    )


@router.get("", response_model=list[MobilityDeviceOut])
def list_mobility_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    is_active: bool | None = Query(default=None),
    device_type: str | None = Query(default=None),
):
    """Lista dispositivos de movilidad del usuario autenticado."""
    query = db.query(MobilityDevice).filter(MobilityDevice.user_id == current_user.id)

    if is_active is not None:
        query = query.filter(MobilityDevice.is_active == is_active)

    if device_type:
        query = query.filter(MobilityDevice.device_type == device_type)

    devices = query.order_by(MobilityDevice.created_at.desc()).all()
    return [_build_mobility_device_out(device) for device in devices]


@router.post("", response_model=MobilityDeviceOut, status_code=status.HTTP_201_CREATED)
def register_mobility_device(
    payload: MobilityDeviceCreateIn,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Registra o actualiza (upsert) un dispositivo de movilidad del usuario."""
    if payload.notification_device_id:
        notification_device = (
            db.query(UserDevice)
            .filter(
                UserDevice.id == payload.notification_device_id,
                UserDevice.user_id == current_user.id,
            )
            .first()
        )
        if not notification_device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="notification_device_id no existe o no pertenece al usuario.",
            )

    now = datetime.now(timezone.utc)

    device: MobilityDevice | None = None
    if payload.external_device_id:
        device = (
            db.query(MobilityDevice)
            .filter(
                MobilityDevice.user_id == current_user.id,
                MobilityDevice.external_device_id == payload.external_device_id,
            )
            .first()
        )

    if device is None and payload.notification_device_id:
        device = (
            db.query(MobilityDevice)
            .filter(
                MobilityDevice.user_id == current_user.id,
                MobilityDevice.notification_device_id == payload.notification_device_id,
            )
            .first()
        )

    created_new = device is None
    if created_new:
        device = MobilityDevice(
            user_id=current_user.id,
            device_type=payload.device_type,
            platform=payload.platform,
            device_name=payload.device_name,
            external_device_id=payload.external_device_id,
            app_version=payload.app_version,
            os_version=payload.os_version,
            last_seen_at=payload.last_seen_at or now,
            is_active=payload.is_active,
            mobility_metadata=payload.metadata,
            updated_at=now,
            notification_device_id=payload.notification_device_id,
        )
        db.add(device)
    else:
        device.device_type = payload.device_type
        device.platform = payload.platform
        device.device_name = payload.device_name
        device.external_device_id = payload.external_device_id
        device.app_version = payload.app_version
        device.os_version = payload.os_version
        device.last_seen_at = payload.last_seen_at or now
        device.is_active = payload.is_active
        device.mobility_metadata = payload.metadata
        device.updated_at = now
        if payload.notification_device_id is not None:
            device.notification_device_id = payload.notification_device_id

        db.add(device)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No fue posible registrar/actualizar el dispositivo de movilidad. "
                "Valida duplicados de notification_device_id y llaves foráneas."
            ),
        ) from exc

    db.refresh(device)
    response.status_code = (
        status.HTTP_201_CREATED if created_new else status.HTTP_200_OK
    )
    return _build_mobility_device_out(device)


@router.get("/{device_id}", response_model=DataResponse[MobilityDeviceOut])
def get_mobility_device(
    device_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Obtiene el detalle de un dispositivo de movilidad."""
    device = MobilityDeviceService.get_device_by_id(db, device_id, current_user)
    return DataResponse(data=_build_mobility_device_out(device))


@router.patch("/{device_id}", response_model=DataResponse[MobilityDeviceOut])
def update_mobility_device(
    device_id: UUID,
    payload: MobilityDeviceUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Actualiza campos editables de un dispositivo de movilidad."""
    device = MobilityDeviceService.get_device_by_id(db, device_id, current_user)
    device = MobilityDeviceService.update_device(db, device, payload)
    return DataResponse(data=_build_mobility_device_out(device))


@router.post("/{device_id}/activate", response_model=DataResponse[MobilityDeviceOut])
def activate_mobility_device(
    device_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Activa un dispositivo de movilidad (is_active = true)."""
    device = MobilityDeviceService.get_device_by_id(db, device_id, current_user)
    device = MobilityDeviceService.activate_device(db, device)
    return DataResponse(data=_build_mobility_device_out(device))


@router.post("/{device_id}/deactivate", response_model=DataResponse[MobilityDeviceOut])
def deactivate_mobility_device(
    device_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Desactiva un dispositivo de movilidad (is_active = false)."""
    device = MobilityDeviceService.get_device_by_id(db, device_id, current_user)
    device = MobilityDeviceService.deactivate_device(db, device)
    return DataResponse(data=_build_mobility_device_out(device))


@router.put(
    "/{device_id}/notification-device", response_model=DataResponse[MobilityDeviceOut]
)
def associate_notification_device(
    device_id: UUID,
    payload: MobilityDeviceNotificationDeviceIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Asocia un dispositivo de notificaciones a un dispositivo de movilidad."""
    device = MobilityDeviceService.get_device_by_id(db, device_id, current_user)
    device = MobilityDeviceService.associate_notification_device(
        db, device, payload.notification_device_id
    )
    return DataResponse(data=_build_mobility_device_out(device))


@router.delete(
    "/{device_id}/notification-device", status_code=status.HTTP_204_NO_CONTENT
)
def dissociate_notification_device(
    device_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Desasocia un dispositivo de notificaciones de un dispositivo de movilidad."""
    device = MobilityDeviceService.get_device_by_id(db, device_id, current_user)
    MobilityDeviceService.dissociate_notification_device(db, device)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

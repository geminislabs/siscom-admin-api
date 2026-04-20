import logging
from datetime import datetime, timezone
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full, get_user_devices_kafka_producer
from app.db.session import get_db
from app.models.user import User
from app.models.user_device import UserDevice
from app.models.user_unit import UserUnit
from app.schemas.user_device import (
    DeviceDeactivateIn,
    DeviceDeactivateOut,
    DeviceRegisterIn,
    DeviceRegisterOut,
)
from app.services.messaging.kafka_producer import UserDevicesKafkaProducer
from app.services.sns import get_or_recreate_endpoint

router = APIRouter()
logger = logging.getLogger(__name__)


def _to_utc_iso_z(value: datetime | None) -> str:
    dt = value or datetime.utcnow()
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"


def _build_user_device_event_payload(
    event_type: str,
    user_id: UUID,
    device_id: str,
    endpoint_arn: str | None,
    unit_id: UUID | None,
    is_active: bool,
    updated_at: datetime | None,
) -> dict:
    return {
        "type": event_type,
        "user_id": str(user_id),
        "device_id": device_id,
        "endpoint_arn": endpoint_arn,
        "unit_id": str(unit_id) if unit_id else None,
        "is_active": is_active,
        "updated_at": _to_utc_iso_z(updated_at),
    }


def _resolve_user_unit_id(db: Session, user_id: UUID) -> UUID | None:
    row = (
        db.query(UserUnit.unit_id)
        .filter(UserUnit.user_id == user_id)
        .order_by(UserUnit.granted_at.desc())
        .first()
    )
    if not row:
        return None
    return row.unit_id


def _publish_user_device_event(
    producer: UserDevicesKafkaProducer,
    payload: dict,
    endpoint: str,
) -> None:
    try:
        published = producer.publish_update(
            payload=payload, key=payload.get("device_id")
        )
    except Exception:
        logger.exception(
            "[USER DEVICES] Excepcion inesperada publicando evento en Kafka.",
            extra={
                "extra_data": {
                    "endpoint": endpoint,
                    "type": payload.get("type"),
                    "user_id": payload.get("user_id"),
                    "device_id": payload.get("device_id"),
                }
            },
        )
        return

    if not published:
        logger.error(
            "[USER DEVICES] Fallo publicando evento en Kafka.",
            extra={
                "extra_data": {
                    "endpoint": endpoint,
                    "type": payload.get("type"),
                    "user_id": payload.get("user_id"),
                    "device_id": payload.get("device_id"),
                }
            },
        )


@router.post("/register", response_model=DeviceRegisterOut)
def register_user_device(
    payload: DeviceRegisterIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    user_devices_kafka_producer: UserDevicesKafkaProducer = Depends(
        get_user_devices_kafka_producer
    ),
):
    now = datetime.now(timezone.utc)
    created_new = False
    device = (
        db.query(UserDevice)
        .filter(UserDevice.device_token == payload.device_token)
        .first()
    )

    # If token rotated (common in iOS), reuse latest user+platform device record.
    if not device:
        device = (
            db.query(UserDevice)
            .filter(
                UserDevice.user_id == current_user.id,
                UserDevice.platform == payload.platform,
            )
            .order_by(UserDevice.updated_at.desc())
            .first()
        )

    try:
        if not device:
            endpoint_arn, _ = get_or_recreate_endpoint(
                device_token=payload.device_token,
                platform=payload.platform,
                endpoint_arn=None,
            )
            device = UserDevice(
                user_id=current_user.id,
                device_token=payload.device_token,
                platform=payload.platform,
                endpoint_arn=endpoint_arn,
                is_active=True,
                last_seen_at=now,
                updated_at=now,
            )
            db.add(device)
            try:
                db.commit()
                db.refresh(device)
                created_new = True
            except IntegrityError:
                # Another concurrent request inserted the same token first.
                db.rollback()
                device = (
                    db.query(UserDevice)
                    .filter(UserDevice.device_token == payload.device_token)
                    .first()
                )
                if not device:
                    raise

            if created_new:
                kafka_payload = _build_user_device_event_payload(
                    event_type="UPSERT",
                    user_id=device.user_id,
                    device_id=device.device_token,
                    endpoint_arn=device.endpoint_arn,
                    unit_id=_resolve_user_unit_id(db, device.user_id),
                    is_active=device.is_active,
                    updated_at=device.updated_at,
                )
                _publish_user_device_event(
                    user_devices_kafka_producer,
                    kafka_payload,
                    endpoint="register_user_device",
                )

                return DeviceRegisterOut(
                    device_token=device.device_token,
                    platform=device.platform,
                    endpoint_arn=device.endpoint_arn,
                    is_active=device.is_active,
                    last_seen_at=device.last_seen_at,
                )

        endpoint_arn, recreated = get_or_recreate_endpoint(
            device_token=payload.device_token,
            platform=payload.platform,
            endpoint_arn=device.endpoint_arn,
        )

        device.user_id = current_user.id
        device.device_token = payload.device_token
        device.platform = payload.platform
        device.is_active = True
        device.last_seen_at = now
        device.updated_at = now

        if recreated or not device.endpoint_arn:
            device.endpoint_arn = endpoint_arn

        db.add(device)
        try:
            db.commit()
            db.refresh(device)
        except IntegrityError:
            # Token was claimed by another row while rotating token/user+platform.
            db.rollback()
            device = (
                db.query(UserDevice)
                .filter(UserDevice.device_token == payload.device_token)
                .first()
            )
            if not device:
                raise

            device.user_id = current_user.id
            device.platform = payload.platform
            device.is_active = True
            device.last_seen_at = now
            device.updated_at = now

            db.add(device)
            db.commit()
            db.refresh(device)

        kafka_payload = _build_user_device_event_payload(
            event_type="UPSERT",
            user_id=device.user_id,
            device_id=device.device_token,
            endpoint_arn=device.endpoint_arn,
            unit_id=_resolve_user_unit_id(db, device.user_id),
            is_active=device.is_active,
            updated_at=device.updated_at,
        )
        _publish_user_device_event(
            user_devices_kafka_producer,
            kafka_payload,
            endpoint="register_user_device",
        )

        return DeviceRegisterOut(
            device_token=device.device_token,
            platform=device.platform,
            endpoint_arn=device.endpoint_arn,
            is_active=device.is_active,
            last_seen_at=device.last_seen_at,
        )
    except (ValueError, RuntimeError, ClientError, BotoCoreError) as exc:
        logger.exception("Error registrando dispositivo en SNS")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "No fue posible registrar el dispositivo en SNS. "
                "Verifica AWS_REGION y los ARN de plataforma SNS."
            ),
        ) from exc


@router.post("/deactivate", response_model=DeviceDeactivateOut)
def deactivate_user_device(
    payload: DeviceDeactivateIn,
    db: Session = Depends(get_db),
    user_devices_kafka_producer: UserDevicesKafkaProducer = Depends(
        get_user_devices_kafka_producer
    ),
):
    device = (
        db.query(UserDevice)
        .filter(UserDevice.device_token == payload.device_token)
        .first()
    )
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispositivo no encontrado",
        )

    device.is_active = False
    device.updated_at = datetime.now(timezone.utc)

    db.add(device)
    db.commit()

    kafka_payload = _build_user_device_event_payload(
        event_type="DELETE",
        user_id=device.user_id,
        device_id=device.device_token,
        endpoint_arn=device.endpoint_arn,
        unit_id=_resolve_user_unit_id(db, device.user_id),
        is_active=False,
        updated_at=device.updated_at,
    )
    _publish_user_device_event(
        user_devices_kafka_producer,
        kafka_payload,
        endpoint="deactivate_user_device",
    )

    return DeviceDeactivateOut(
        message="Dispositivo desactivado exitosamente",
        device_token=payload.device_token,
        is_active=False,
    )

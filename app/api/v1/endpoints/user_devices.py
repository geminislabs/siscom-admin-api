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
from app.schemas.user_device import (
    DeviceDeactivateIn,
    DeviceDeactivateOut,
    DeviceRegisterIn,
    DeviceRegisterOut,
)
from app.services.messaging.control_events import (
    build_user_device_event,
    publish_control_event,
)
from app.services.messaging.kafka_producer import UserDevicesKafkaProducer
from app.services.sns import get_or_recreate_endpoint

router = APIRouter()
logger = logging.getLogger(__name__)


def _user_device_payload(
    *,
    event_type: str,
    organization_id: UUID | None,
    device: UserDevice,
) -> dict:
    return build_user_device_event(
        event_type=event_type,
        organization_id=organization_id,
        device_row_id=device.id,
        user_id=device.user_id,
        device_token=device.device_token,
        platform=device.platform,
        endpoint_arn=device.endpoint_arn,
        is_active=device.is_active,
        updated_at=device.updated_at,
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

    # La fila propia de este usuario: por token exacto, o por plataforma si el
    # token rotó (frecuente en iOS). La búsqueda nunca sale de current_user —
    # buscar primero por device_token a secas es lo que le quitaba el push a
    # quien ya no es dueño de la sesión en un aparato compartido (ver el
    # comentario de /deactivate sobre el par (device_token, user_id)).
    device = (
        db.query(UserDevice)
        .filter(
            UserDevice.user_id == current_user.id,
            UserDevice.device_token == payload.device_token,
        )
        .first()
    )
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
            # Aparato compartido: si otra cuenta ya tenía este token activo, se
            # desactiva su fila —con su propio evento— en vez de reasignarla.
            # Antes, la fila cambiaba de dueño en silencio: el usuario anterior
            # dejaba de recibir push sin ningún rastro, ni siquiera en Kafka.
            other_owner = (
                db.query(UserDevice)
                .filter(
                    UserDevice.device_token == payload.device_token,
                    UserDevice.user_id != current_user.id,
                    UserDevice.is_active.is_(True),
                )
                .first()
            )
            if other_owner:
                other_owner.is_active = False
                other_owner.updated_at = now
                db.add(other_owner)
                db.commit()
                db.refresh(other_owner)

                other_owner_user = (
                    db.query(User).filter(User.id == other_owner.user_id).first()
                )
                publish_control_event(
                    user_devices_kafka_producer,
                    _user_device_payload(
                        event_type="DELETE",
                        organization_id=(
                            other_owner_user.organization_id
                            if other_owner_user
                            else None
                        ),
                        device=other_owner,
                    ),
                    key=str(other_owner.id),
                    endpoint="register_user_device",
                )

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
                # Another concurrent request inserted the same (user, token) first.
                db.rollback()
                device = (
                    db.query(UserDevice)
                    .filter(
                        UserDevice.user_id == current_user.id,
                        UserDevice.device_token == payload.device_token,
                    )
                    .first()
                )
                if not device:
                    raise

            if created_new:
                publish_control_event(
                    user_devices_kafka_producer,
                    _user_device_payload(
                        event_type="UPSERT",
                        organization_id=current_user.organization_id,
                        device=device,
                    ),
                    key=str(device.id),
                    endpoint="register_user_device",
                )

                return DeviceRegisterOut(
                    id=device.id,
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

        # `device` ya es una fila de current_user — las dos búsquedas de arriba
        # están acotadas a su user_id, así que no hay reasignación que hacer.
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
            # Fila concurrente insertada para el mismo (user, token) primero.
            db.rollback()
            device = (
                db.query(UserDevice)
                .filter(
                    UserDevice.user_id == current_user.id,
                    UserDevice.device_token == payload.device_token,
                )
                .first()
            )
            if not device:
                raise

            device.platform = payload.platform
            device.is_active = True
            device.last_seen_at = now
            device.updated_at = now

            db.add(device)
            db.commit()
            db.refresh(device)

        publish_control_event(
            user_devices_kafka_producer,
            _user_device_payload(
                event_type="UPSERT",
                organization_id=current_user.organization_id,
                device=device,
            ),
            key=str(device.id),
            endpoint="register_user_device",
        )

        return DeviceRegisterOut(
            id=device.id,
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
    current_user: User = Depends(get_current_user_full),
    user_devices_kafka_producer: UserDevicesKafkaProducer = Depends(
        get_user_devices_kafka_producer
    ),
):
    # Este endpoint no pedía credencial ninguna, y la omisión no era visible:
    # no la declaraba ni la firma ni el montaje del router.
    #
    # Medido el 26/09/2026, y las dos mitades importan. Contra **producción**,
    # una petición sin cabecera con un token inventado devolvió `404
    # «Dispositivo no encontrado»` mientras `GET /users/me` devolvía 401: la
    # búsqueda se ejecutaba, así que no había guardián. Contra **este mismo
    # código** con la fila presente, los dos tests hostiles de abajo devolvían
    # `200`. O sea: el 404 era sólo la rama del token inexistente, y con un
    # token que existe **la baja se ejecutaba**. No era un oráculo, era una
    # escritura sin autenticar — y el 404/200 servía además para saber si un
    # token existe.
    #
    # La fila se busca por el **par** `(device_token, user_id)`, no sólo por el
    # token, y eso es la mitad del arreglo:
    #
    #   1. Exigir sesión sin acotar el alcance cambiaría «cualquiera» por
    #      «cualquier usuario», que no es cerrar nada: una credencial válida de
    #      quien no es dueño seguiría dando de baja el aparato de otro.
    #   2. Es la forma que pide el multi-cuenta. Hasta el 30/09/2026, `register`
    #      reasignaba el dueño del token en silencio, así que entrar con la
    #      segunda cuenta apagaba el push de la primera sin dejar rastro. Ya
    #      no: ahora desactiva la fila anterior con su propio evento en vez de
    #      reasignarla, así que esta consulta (por el par) era, y sigue siendo,
    #      la forma correcta de buscar.
    device = (
        db.query(UserDevice)
        .filter(
            UserDevice.device_token == payload.device_token,
            UserDevice.user_id == current_user.id,
        )
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

    # El dueño de la fila es quien pide la baja —lo impone el filtro de arriba—,
    # así que la consulta que resolvía la organización desde `device.user_id`
    # sobra: es la misma.
    publish_control_event(
        user_devices_kafka_producer,
        _user_device_payload(
            event_type="DELETE",
            organization_id=current_user.organization_id,
            device=device,
        ),
        key=str(device.id),
        endpoint="deactivate_user_device",
    )

    return DeviceDeactivateOut(
        message="Dispositivo desactivado exitosamente",
        device_token=payload.device_token,
        is_active=False,
    )

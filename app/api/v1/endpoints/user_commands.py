import base64
import hashlib
import hmac
import logging
import re

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full
from app.core.config import settings
from app.db.session import get_db
from app.models.command import Command
from app.models.device import Device
from app.models.unified_sim_profile import UnifiedSimProfile
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.models.user import User
from app.schemas.command import CommandResponse
from app.schemas.user_command import UserCommandCreate, UserCommandType
from app.services.kore import KoreAuthError, KoreSmsError, kore_service

logger = logging.getLogger(__name__)

router = APIRouter()


cognito_client_kwargs = {"region_name": settings.COGNITO_REGION}
if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
    cognito_client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    cognito_client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
if getattr(settings, "COGNITO_ENDPOINT", None):
    cognito_client_kwargs["endpoint_url"] = settings.COGNITO_ENDPOINT
cognito = boto3.client("cognito-idp", **cognito_client_kwargs)


def _get_secret_hash(username: str) -> str:
    message = bytes(username + settings.COGNITO_CLIENT_ID, "utf-8")
    secret = bytes(settings.COGNITO_CLIENT_SECRET, "utf-8")
    dig = hmac.new(secret, msg=message, digestmod=hashlib.sha256).digest()
    return base64.b64encode(dig).decode()


def _validate_user_password(email: str, password: str) -> bool:
    try:
        auth_params = {
            "USERNAME": email,
            "PASSWORD": password,
            "SECRET_HASH": _get_secret_hash(email),
        }

        response = cognito.initiate_auth(
            ClientId=settings.COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters=auth_params,
        )

        return bool(response.get("AuthenticationResult"))
    except ClientError as e:
        error_code = e.response["Error"].get("Code")
        if error_code in {
            "NotAuthorizedException",
            "UserNotFoundException",
            "UserNotConfirmedException",
        }:
            return False
        logger.error(
            f"[USER COMMANDS] Error validando credenciales en Cognito: {error_code}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo validar la contraseña en este momento",
        )


def _build_command_for_device(command_type: UserCommandType, device: Device) -> str:
    brand = (device.brand or "").strip().lower()
    model = (device.model or "").strip().upper()
    suntech_supported_pattern = r"^ST4\d{3}[A-Z]*$"

    if brand == "suntech" and re.match(suntech_supported_pattern, model):
        if command_type == UserCommandType.ENGINE_STOP:
            return f"AT^CMD;{device.device_id};04;01"
        if command_type == UserCommandType.ENGINE_RESUME:
            return f"AT^CMD;{device.device_id};04;02"

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            "No se pudo formar el comando para el modelo del equipo. "
            f"Modelo actual: brand='{device.brand}', model='{device.model}'. "
            "Actualmente se soportan modelos Suntech con patrón ST4 + 3 dígitos "
            "(ej: ST4330, ST4315, ST4315U)"
        ),
    )


@router.post("", response_model=CommandResponse, status_code=status.HTTP_201_CREATED)
async def create_user_command(
    command_in: UserCommandCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    if not current_user.is_master:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el usuario master puede ejecutar este endpoint",
        )

    if command_in.command_type == UserCommandType.ENGINE_STOP:
        if not command_in.confirmation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ENGINE_STOP requiere confirmation",
            )
        if not command_in.confirmation.accepted_risk:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debe confirmar accepted_risk=true para ENGINE_STOP",
            )
        if not _validate_user_password(
            current_user.email,
            command_in.confirmation.password,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Contraseña inválida",
            )

    unit = (
        db.query(Unit)
        .filter(
            Unit.id == command_in.unit_id,
            Unit.organization_id == current_user.organization_id,
            Unit.deleted_at.is_(None),
        )
        .first()
    )
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unidad no encontrada",
        )

    assignment = (
        db.query(UnitDevice)
        .filter(
            UnitDevice.unit_id == unit.id,
            UnitDevice.unassigned_at.is_(None),
        )
        .order_by(UnitDevice.assigned_at.desc())
        .first()
    )
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La unidad no tiene un dispositivo asignado",
        )

    device = db.query(Device).filter(Device.device_id == assignment.device_id).first()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispositivo no encontrado para la unidad",
        )

    raw_command = _build_command_for_device(command_in.command_type, device)

    command_metadata = {
        "source_id": "user_commands",
        "command_type": command_in.command_type.value,
        "unit_id": str(unit.id),
    }

    command = Command(
        command=raw_command,
        media="KORE_SMS_API",
        request_user_id=current_user.id,
        request_user_email=current_user.email,
        device_id=device.device_id,
        command_metadata=command_metadata,
        status="pending",
    )

    db.add(command)
    db.commit()
    db.refresh(command)

    sim_profile = (
        db.query(UnifiedSimProfile)
        .filter(UnifiedSimProfile.device_id == device.device_id)
        .first()
    )
    if not sim_profile or not sim_profile.kore_sim_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El dispositivo no tiene una SIM KORE configurada",
        )

    kore_error = None

    if kore_service.is_configured():
        try:
            auth_response = await kore_service.authenticate()

            sms_response = await kore_service.send_sms_command(
                kore_sim_id=sim_profile.kore_sim_id,
                payload=raw_command,
                access_token=auth_response.access_token,
            )

            if sms_response.success:
                command.status = "sent"
                if command.command_metadata is None:
                    command.command_metadata = {}
                command.command_metadata["kore_response"] = sms_response.response_data
                command.command_metadata["kore_sim_id"] = sim_profile.kore_sim_id
            else:
                kore_error = sms_response.message

        except KoreAuthError as e:
            kore_error = f"Error de autenticación KORE: {str(e)}"

        except KoreSmsError as e:
            kore_error = f"Error SMS KORE: {str(e)}"

        except Exception as e:
            kore_error = f"Error inesperado KORE: {str(e)}"
            logger.exception(f"[USER COMMANDS] {kore_error}")

        if kore_error:
            if command.command_metadata is None:
                command.command_metadata = {}
            command.command_metadata["kore_error"] = kore_error

        db.commit()
        db.refresh(command)

    return CommandResponse(command_id=command.command_id, status=command.status)

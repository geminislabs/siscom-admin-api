import base64
import hashlib
import hmac
import logging
import re
from typing import Any, Optional
from uuid import UUID

import boto3
import httpx
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from app.schemas.command import (
    CommandListResponse,
    CommandOut,
    CommandResponse,
    CommandSyncOut,
)
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


def _require_master(current_user: User) -> None:
    if not current_user.is_master:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el usuario master puede ejecutar este endpoint",
        )


def _find_user_command_for_org(
    db: Session, command_id: UUID, organization_id: UUID
) -> Optional[Command]:
    return (
        db.query(Command)
        .join(Device, Device.device_id == Command.device_id)
        .filter(
            Command.command_id == command_id,
            Device.organization_id == organization_id,
            Command.command_metadata.isnot(None),
            Command.command_metadata["source_id"].astext == "user_commands",
        )
        .first()
    )


@router.post("", response_model=CommandResponse, status_code=status.HTTP_201_CREATED)
async def create_user_command(
    command_in: UserCommandCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    _require_master(current_user)

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
                updated_metadata = dict(command.command_metadata or {})
                updated_metadata["kore_response"] = sms_response.response_data
                updated_metadata["kore_sim_id"] = sim_profile.kore_sim_id
                command.command_metadata = updated_metadata
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
            updated_metadata = dict(command.command_metadata or {})
            updated_metadata["kore_error"] = kore_error
            command.command_metadata = updated_metadata

        db.commit()
        db.refresh(command)

    return CommandResponse(command_id=command.command_id, status=command.status)


@router.get("/unit/{unit_id}", response_model=CommandListResponse)
def get_user_commands_by_unit(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    status_filter: Optional[str] = Query(
        None, description="Filtrar por estado (pending, sent, delivered, failed)"
    ),
    limit: int = Query(50, ge=1, le=500, description="Límite de resultados"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
):
    _require_master(current_user)

    unit = (
        db.query(Unit)
        .filter(
            Unit.id == unit_id,
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

    query = (
        db.query(Command)
        .join(Device, Device.device_id == Command.device_id)
        .filter(
            Device.organization_id == current_user.organization_id,
            Command.command_metadata.isnot(None),
            Command.command_metadata["source_id"].astext == "user_commands",
            Command.command_metadata["unit_id"].astext == str(unit_id),
        )
    )

    if status_filter:
        if status_filter not in ["pending", "sent", "delivered", "failed"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Estado inválido. Valores válidos: pending, sent, delivered, failed",
            )
        query = query.filter(Command.status == status_filter)

    total = query.count()
    commands = (
        query.order_by(Command.requested_at.desc()).offset(offset).limit(limit).all()
    )

    commands_out = [
        CommandOut(
            command_id=cmd.command_id,
            template_id=cmd.template_id,
            command=cmd.command,
            media=cmd.media,
            request_user_id=cmd.request_user_id,
            request_user_email=cmd.request_user_email,
            device_id=cmd.device_id,
            requested_at=cmd.requested_at,
            updated_at=cmd.updated_at,
            status=cmd.status,
            command_metadata=cmd.command_metadata,
        )
        for cmd in commands
    ]

    return CommandListResponse(commands=commands_out, total=total)


@router.post("/{command_id}/sync", response_model=CommandSyncOut)
async def sync_user_command(
    command_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    _require_master(current_user)

    command = _find_user_command_for_org(db, command_id, current_user.organization_id)
    if not command:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comando user-command no encontrado",
        )

    if command.media != "KORE_SMS_API":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Sincronización no implementada para media '{command.media}'. "
            f"Solo se soporta 'KORE_SMS_API'",
        )

    metadata = command.command_metadata
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El comando no tiene metadata",
        )

    kore_response = metadata.get("kore_response")
    if not kore_response:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El comando no tiene kore_response en metadata",
        )

    sid = kore_response.get("sid")
    url = kore_response.get("url")

    if not sid or not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El kore_response no contiene 'sid' o 'url'",
        )

    sync_response: Optional[dict[str, Any]] = None
    sync_error: Optional[str] = None

    try:
        if not kore_service._cached_token:
            await kore_service.authenticate()

        access_token = kore_service._cached_token
        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)

            if response.status_code == 401:
                await kore_service.authenticate()
                access_token = kore_service._cached_token
                headers["Authorization"] = f"Bearer {access_token}"
                response = await client.get(url, headers=headers)

            try:
                sync_response = response.json()
            except Exception:
                sync_response = {"raw_response": response.text}

    except KoreAuthError as e:
        sync_error = f"Error de autenticación KORE: {str(e)}"
        logger.error(f"[USER COMMANDS SYNC] {sync_error}")

    except httpx.RequestError as e:
        sync_error = f"Error de conexión con KORE: {str(e)}"
        logger.error(f"[USER COMMANDS SYNC] {sync_error}")

    except Exception as e:
        sync_error = f"Error inesperado: {str(e)}"
        logger.exception(f"[USER COMMANDS SYNC] {sync_error}")

    if sync_response or sync_error:
        if command.command_metadata is None:
            command.command_metadata = {}

        updated_metadata = dict(command.command_metadata)

        if sync_response:
            updated_metadata["sync_response"] = sync_response
            kore_status = sync_response.get("status")
            if kore_status in ["pending", "sent", "delivered", "failed"]:
                command.status = kore_status

        if sync_error:
            updated_metadata["sync_error"] = sync_error

        command.command_metadata = updated_metadata
        db.commit()
        db.refresh(command)

    if sync_error and not sync_response:
        sync_response = {"error": sync_error}

    return CommandSyncOut(
        command_id=command.command_id,
        template_id=command.template_id,
        command=command.command,
        media=command.media,
        request_user_id=command.request_user_id,
        request_user_email=command.request_user_email,
        device_id=command.device_id,
        requested_at=command.requested_at,
        updated_at=command.updated_at,
        status=command.status,
        command_metadata=command.command_metadata,
        sync_response=sync_response,
    )

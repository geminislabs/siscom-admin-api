import logging
import re
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user_full,
    get_identity_provider,
    get_request_locale,
)
from app.core.i18n import t
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
from app.services.identity import (
    CredencialesInvalidas,
    CredencialNoEncontrada,
    CredencialSinConfirmar,
    ErrorDeIdentidad,
    IdentityProvider,
)
from app.services.kore import KoreAuthError, KoreSmsError, kore_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _validate_user_password(
    idp: IdentityProvider, user: User, password: str, locale: str = "es"
) -> bool:
    """Si esa contraseña es la del usuario.

    Es la confirmación de un `ENGINE_STOP`: apagar el motor de un vehículo en
    marcha se pide dos veces, y la segunda con la contraseña. Un fallo del
    proveedor no puede colarse como "sí" ni como "no": lo primero autorizaría
    la orden sin credencial, lo segundo culparía al usuario de una caída.
    """
    try:
        idp.autenticar(handle=user.external_id, password=password)
        return True
    except (
        CredencialesInvalidas,
        CredencialNoEncontrada,
        CredencialSinConfirmar,
    ):
        return False
    except ErrorDeIdentidad as e:
        logger.error(
            "user_commands.credential_check_failed",
            extra={"error_code": e.codigo},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=t("user_commands.password_validation_unavailable", locale),
        )


def _build_command_for_device(
    command_type: UserCommandType, device: Device, locale: str = "es"
) -> str:
    brand = (device.brand or "").strip().lower()
    model = (device.model or "").strip().upper()
    suntech_supported_pattern = r"^ST4\d{3}[A-Z]*$"

    if brand == "suntech" and re.match(suntech_supported_pattern, model):
        if command_type == UserCommandType.ENGINE_STOP:
            return f"AT^CMD;{device.device_id};04;01"
        if command_type == UserCommandType.ENGINE_RESUME:
            return f"AT^CMD;{device.device_id};04;02"

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=t(
            "user_commands.unsupported_device_model",
            locale,
            brand=device.brand,
            model=device.model,
        ),
    )


def _require_master(current_user: User, locale: str = "es") -> None:
    if not current_user.is_active_organization_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=t("user_commands.only_master", locale),
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
    idp: IdentityProvider = Depends(get_identity_provider),
    locale: str = Depends(get_request_locale),
):
    _require_master(current_user, locale)

    if command_in.command_type == UserCommandType.ENGINE_STOP:
        if not command_in.confirmation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=t("user_commands.engine_stop_requires_confirmation", locale),
            )
        if not command_in.confirmation.accepted_risk:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=t("user_commands.engine_stop_requires_accepted_risk", locale),
            )
        if not _validate_user_password(
            idp,
            current_user,
            command_in.confirmation.password,
            **({"locale": locale} if locale != "es" else {}),
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=t("user_commands.invalid_password", locale),
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
            detail=t("user_commands.unit_not_found", locale),
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
            detail=t("user_commands.unit_has_no_device", locale),
        )

    device = db.query(Device).filter(Device.device_id == assignment.device_id).first()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("user_commands.device_not_found_for_unit", locale),
        )

    raw_command = _build_command_for_device(command_in.command_type, device, locale)

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
            detail=t("user_commands.device_has_no_kore_sim", locale),
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
            logger.exception(
                "user_commands.kore_unexpected",
                extra={"error_type": type(e).__name__},
            )

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
    locale: str = Depends(get_request_locale),
):
    _require_master(current_user, locale)

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
            detail=t("user_commands.unit_not_found", locale),
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
                detail=t("user_commands.invalid_status_filter", locale),
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
    locale: str = Depends(get_request_locale),
):
    _require_master(current_user, locale)

    command = _find_user_command_for_org(db, command_id, current_user.organization_id)
    if not command:
        diagnostic_command = (
            db.query(Command).filter(Command.command_id == command_id).first()
        )
        if not diagnostic_command:
            logger.warning(
                "user_commands.sync_not_found",
                extra={"command_id": str(command_id)},
            )
        else:
            diagnostic_device = (
                db.query(Device)
                .filter(Device.device_id == diagnostic_command.device_id)
                .first()
            )
            diagnostic_org_id = (
                str(diagnostic_device.organization_id) if diagnostic_device else None
            )
            source_id = None
            if isinstance(diagnostic_command.command_metadata, dict):
                source_id = diagnostic_command.command_metadata.get("source_id")

            logger.warning(
                "user_commands.sync_not_accessible",
                extra={
                    "command_id": str(command_id),
                    "organization_id": str(current_user.organization_id),
                    "command_org_id": diagnostic_org_id,
                    "source_id": source_id,
                },
            )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("user_commands.command_not_found", locale),
        )

    if command.media != "KORE_SMS_API":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=t("commands.sync_not_implemented", locale, media=command.media),
        )

    metadata = command.command_metadata
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("commands.missing_metadata", locale),
        )

    kore_response = metadata.get("kore_response")
    if not kore_response:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("commands.missing_kore_response", locale),
        )

    sid = kore_response.get("sid")
    url = kore_response.get("url")

    if not sid or not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("commands.missing_sid_or_url", locale),
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
        logger.error(
            "user_commands.sync_auth_failed",
            extra={"error_type": type(e).__name__},
        )

    except httpx.RequestError as e:
        sync_error = f"Error de conexión con KORE: {str(e)}"
        logger.error(
            "user_commands.sync_network_error",
            extra={"error_type": type(e).__name__},
        )

    except Exception as e:
        sync_error = f"Error inesperado: {str(e)}"
        logger.exception(
            "user_commands.sync_unexpected",
            extra={"error_type": type(e).__name__},
        )

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

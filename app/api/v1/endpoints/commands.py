import logging
from typing import Any, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_cognito_or_paseto
from app.db.session import get_db
from app.models.command import Command
from app.models.device import Device
from app.models.unified_sim_profile import UnifiedSimProfile
from app.schemas.command import (
    CommandCreate,
    CommandListResponse,
    CommandOut,
    CommandResponse,
    CommandSyncOut,
)
from app.services.kore import KoreAuthError, KoreSmsError, kore_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Dependencia para autenticación dual (Cognito o PASETO)
get_auth_for_commands = get_auth_cognito_or_paseto(
    required_service="gac",
    required_role="GAC_ADMIN",
)


@router.post("", response_model=CommandResponse, status_code=status.HTTP_201_CREATED)
async def create_command(
    command_in: CommandCreate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_commands),
):
    """
    Crea un nuevo comando para enviar a un dispositivo.

    **Autenticación:**
    - Token de Cognito: Usuario autenticado del sistema
    - Token PASETO: Requiere service="gac" y role="GAC_ADMIN"

    **Parámetros:**
    - `command`: El comando a enviar al dispositivo
    - `media`: Medio de comunicación (sms, tcp, etc.)
    - `device_id`: ID del dispositivo destino
    - `template_id`: (Opcional) ID del template de comando
    - `command_metadata`: (Opcional) Datos adicionales del comando

    **Comportamiento:**
    - Si el dispositivo tiene una SIM con kore_sim_id configurado,
      el comando se enviará automáticamente vía KORE SMS.

    **Retorna:**
    - `command_id`: UUID del comando creado
    - `status`: Estado del comando ('pending', 'sent', o 'failed')
    """
    # Verificar que el dispositivo existe
    device = db.query(Device).filter(Device.device_id == command_in.device_id).first()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispositivo no encontrado",
        )

    # Obtener email según el tipo de autenticación
    # Para Cognito: obtener email del payload del token
    # Para PASETO: obtener email del payload
    request_user_email: str
    request_user_id = None

    if auth.auth_type == "cognito":
        # Obtener email del token Cognito
        request_user_email = auth.payload.get("email")
        request_user_id = auth.user_id
        if not request_user_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token Cognito inválido: falta el campo 'email'",
            )
    else:  # paseto
        request_user_email = auth.payload.get("email")
        if not request_user_email:
            # Tokens generados antes de incluir email usan el nombre del servicio como fallback
            service = auth.payload.get("service", "unknown")
            request_user_email = f"{service}@internal"

    # Crear el comando
    command = Command(
        template_id=command_in.template_id,
        command=command_in.command,
        media=command_in.media,
        request_user_id=request_user_id,
        request_user_email=request_user_email,
        device_id=command_in.device_id,
        command_metadata=command_in.command_metadata,
        status="pending",
    )

    db.add(command)
    db.commit()
    db.refresh(command)

    # Intentar enviar el comando vía KORE si está configurado
    kore_error = None

    if kore_service.is_configured():
        # Consultar la vista unified_sim_profiles para obtener kore_sim_id
        sim_profile = (
            db.query(UnifiedSimProfile)
            .filter(UnifiedSimProfile.device_id == command_in.device_id)
            .first()
        )

        if sim_profile and sim_profile.kore_sim_id:
            logger.info(
                f"[COMMANDS] Enviando comando vía KORE para device_id={command_in.device_id}, "
                f"kore_sim_id={sim_profile.kore_sim_id}"
            )

            try:
                # Autenticar con KORE
                auth_response = await kore_service.authenticate()

                # Enviar el comando SMS
                sms_response = await kore_service.send_sms_command(
                    kore_sim_id=sim_profile.kore_sim_id,
                    payload=command_in.command,
                    access_token=auth_response.access_token,
                )

                if sms_response.success:
                    # Actualizar estado del comando a 'sent'
                    command.status = "sent"
                    # Guardar metadata de la respuesta de KORE
                    if command.command_metadata is None:
                        command.command_metadata = {}
                    command.command_metadata["kore_response"] = (
                        sms_response.response_data
                    )
                    command.command_metadata["kore_sim_id"] = sim_profile.kore_sim_id
                    logger.info(
                        f"[COMMANDS] Comando enviado exitosamente vía KORE: "
                        f"command_id={command.command_id}"
                    )
                else:
                    # Error al enviar, mantener como pending o marcar como failed
                    kore_error = sms_response.message
                    logger.warning(
                        f"[COMMANDS] Error KORE al enviar comando: {kore_error}"
                    )

            except KoreAuthError as e:
                kore_error = f"Error de autenticación KORE: {str(e)}"
                logger.error(f"[COMMANDS] {kore_error}")

            except KoreSmsError as e:
                kore_error = f"Error SMS KORE: {str(e)}"
                logger.error(f"[COMMANDS] {kore_error}")

            except Exception as e:
                kore_error = f"Error inesperado KORE: {str(e)}"
                logger.exception(f"[COMMANDS] {kore_error}")

            # Guardar error en metadata si hubo
            if kore_error:
                if command.command_metadata is None:
                    command.command_metadata = {}
                command.command_metadata["kore_error"] = kore_error

            db.commit()
            db.refresh(command)

    return CommandResponse(
        command_id=command.command_id,
        status=command.status,
    )


@router.get("/device/{device_id}", response_model=CommandListResponse)
def get_commands_by_device(
    device_id: str,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_commands),
    status_filter: Optional[str] = Query(
        None, description="Filtrar por estado (pending, sent, delivered, failed)"
    ),
    limit: int = Query(50, ge=1, le=500, description="Límite de resultados"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
):
    """
    Obtiene todos los comandos enviados a un dispositivo específico.

    **Autenticación:**
    - Token de Cognito: Usuario autenticado del sistema
    - Token PASETO: Requiere service="gac" y role="GAC_ADMIN"

    **Parámetros:**
    - `device_id`: ID del dispositivo
    - `status_filter`: (Opcional) Filtrar por estado
    - `limit`: Límite de resultados (default: 50, max: 500)
    - `offset`: Offset para paginación

    **Retorna:**
    - Lista de comandos con información completa
    - Total de comandos encontrados
    """
    # Verificar que el dispositivo existe
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispositivo no encontrado",
        )

    # Construir query base
    query = db.query(Command).filter(Command.device_id == device_id)

    # Aplicar filtro de estado si se proporciona
    if status_filter:
        if status_filter not in ["pending", "sent", "delivered", "failed"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Estado inválido. Valores válidos: pending, sent, delivered, failed",
            )
        query = query.filter(Command.status == status_filter)

    # Contar total
    total = query.count()

    # Obtener comandos con paginación
    commands = (
        query.order_by(Command.requested_at.desc()).offset(offset).limit(limit).all()
    )

    # Construir respuesta
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


@router.get("/{command_id}", response_model=CommandOut)
def get_command(
    command_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_commands),
):
    """
    Obtiene el detalle de un comando específico por su ID.

    **Autenticación:**
    - Token de Cognito: Usuario autenticado del sistema
    - Token PASETO: Requiere service="gac" y role="GAC_ADMIN"

    **Parámetros:**
    - `command_id`: UUID del comando

    **Retorna:**
    - Información completa del comando
    """
    command = db.query(Command).filter(Command.command_id == command_id).first()

    if not command:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comando no encontrado",
        )

    return CommandOut(
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
    )


@router.post("/{command_id}/sync", response_model=CommandSyncOut)
async def sync_command(
    command_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_commands),
):
    """
    Sincroniza el estado de un comando con KORE.

    **Autenticación:**
    - Token de Cognito: Usuario autenticado del sistema
    - Token PASETO: Requiere service="gac" y role="GAC_ADMIN"

    **Parámetros:**
    - `command_id`: UUID del comando a sincronizar

    **Comportamiento:**
    - Solo soporta comandos con media="KORE_SMS_API"
    - Consulta el estado del SMS en KORE usando la URL almacenada en metadata
    - Actualiza el metadata del comando con la respuesta de KORE

    **Retorna:**
    - Información completa del comando + sync_response con la respuesta de KORE
    """
    # 1. Consultar el comando en la BD
    command = db.query(Command).filter(Command.command_id == command_id).first()

    if not command:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comando no encontrado",
        )

    # 3. Verificar que el media sea "KORE_SMS_API"
    if command.media != "KORE_SMS_API":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Sincronización no implementada para media '{command.media}'. "
            f"Solo se soporta 'KORE_SMS_API'",
        )

    # 2.1 Obtener el metadata
    metadata = command.command_metadata
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El comando no tiene metadata",
        )

    # 2.2 y 2.3 Extraer sid y url de kore_response
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

    logger.info(
        f"[COMMANDS SYNC] Sincronizando comando {command_id}, sid={sid}, url={url}"
    )

    # 2.3 Loguearse en KORE (solo si no hay sesión activa)
    sync_response: Optional[dict[str, Any]] = None
    sync_error: Optional[str] = None

    try:
        # Verificar si hay token cacheado, si no, autenticar
        if not kore_service._cached_token:
            logger.info("[COMMANDS SYNC] No hay token cacheado, autenticando con KORE")
            await kore_service.authenticate()

        access_token = kore_service._cached_token

        # 2.4 Ejecutar la solicitud GET a la URL de KORE
        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)

            # Si el token expiró (401), re-autenticar e intentar de nuevo
            if response.status_code == 401:
                logger.info("[COMMANDS SYNC] Token expirado, re-autenticando con KORE")
                await kore_service.authenticate()
                access_token = kore_service._cached_token
                headers["Authorization"] = f"Bearer {access_token}"
                response = await client.get(url, headers=headers)

            try:
                sync_response = response.json()
            except Exception:
                sync_response = {"raw_response": response.text}

            if response.status_code not in (200, 201, 202):
                logger.warning(
                    f"[COMMANDS SYNC] Respuesta no exitosa de KORE: "
                    f"status={response.status_code}, body={response.text}"
                )

            logger.info(
                f"[COMMANDS SYNC] Respuesta de KORE: status={response.status_code}"
            )

    except KoreAuthError as e:
        sync_error = f"Error de autenticación KORE: {str(e)}"
        logger.error(f"[COMMANDS SYNC] {sync_error}")

    except httpx.RequestError as e:
        sync_error = f"Error de conexión con KORE: {str(e)}"
        logger.error(f"[COMMANDS SYNC] {sync_error}")

    except Exception as e:
        sync_error = f"Error inesperado: {str(e)}"
        logger.exception(f"[COMMANDS SYNC] {sync_error}")

    # 2.5 Actualizar el registro en la BD con el response
    # Agregar salto de línea y el nuevo response sin perder el anterior
    if sync_response or sync_error:
        if command.command_metadata is None:
            command.command_metadata = {}

        # Crear una copia del metadata para modificarlo
        updated_metadata = dict(command.command_metadata)

        # Agregar la respuesta de sync
        if sync_response:
            updated_metadata["sync_response"] = sync_response

            # Actualizar el status del comando si viene en el response de KORE
            kore_status = sync_response.get("status")
            if kore_status:
                command.status = kore_status
                logger.info(
                    f"[COMMANDS SYNC] Status del comando actualizado a: {kore_status}"
                )

        if sync_error:
            updated_metadata["sync_error"] = sync_error

        command.command_metadata = updated_metadata
        db.commit()
        db.refresh(command)

    # Si hubo error, incluirlo en la respuesta pero no fallar
    if sync_error and not sync_response:
        sync_response = {"error": sync_error}

    # 2.6 Retornar la información del comando con sync_response
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

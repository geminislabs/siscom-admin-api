"""
Endpoints para el módulo de contacto.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.schemas.contact import ContactMessageCreate, ContactMessageResponse
from app.services.notifications import send_contact_email
from app.utils.recaptcha import verify_recaptcha

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/send-message",
    response_model=ContactMessageResponse,
    status_code=status.HTTP_200_OK,
)
async def send_contact_message(message: ContactMessageCreate):
    """
    Envía un mensaje de contacto al email configurado.

    - **nombre**: Nombre de la persona que contacta (requerido)
    - **correo_electronico**: Email de contacto (opcional si se proporciona teléfono)
    - **telefono**: Teléfono de contacto (opcional si se proporciona email)
    - **mensaje**: Contenido del mensaje (requerido)

    Nota: Debe proporcionar al menos correo_electronico o telefono.
    """
    # Validar que CONTACT_EMAIL esté configurado
    if not settings.CONTACT_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de contacto no está configurado. Por favor contacte al administrador.",
        )

    # Verificar reCAPTCHA v3
    try:
        await verify_recaptcha(message.recaptcha_token, min_score=0.5)
    except HTTPException as e:
        # Re-raise la excepción de reCAPTCHA
        raise e
    except Exception as e:
        logger.error(
            "contact.recaptcha_error",
            extra={"error_type": type(e).__name__},
        )
        raise HTTPException(
            status_code=500,
            detail="Error al verificar la seguridad. Por favor intenta más tarde.",
        )

    try:
        # Enviar el email de contacto
        success = send_contact_email(
            nombre=message.nombre,
            correo_electronico=message.correo_electronico,
            telefono=message.telefono,
            mensaje=message.mensaje,
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No se pudo enviar el mensaje de contacto. Por favor intente más tarde.",
            )

        return ContactMessageResponse(
            success=True,
            message="Mensaje de contacto enviado exitosamente. Nos pondremos en contacto contigo pronto.",
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception:
        logger.exception("contact.submit_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar el mensaje de contacto",
        )

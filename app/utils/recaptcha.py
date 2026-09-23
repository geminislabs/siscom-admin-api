"""
Utilidad para verificar reCAPTCHA v3 de Google.
"""

import logging

import httpx
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)


async def verify_recaptcha(token: str, min_score: float = 0.5) -> dict:
    """
    Verifica el token de reCAPTCHA v3 con Google.

    Args:
        token: Token de reCAPTCHA recibido del frontend
        min_score: Score mínimo requerido (0.0 a 1.0). Default: 0.5
                  - 1.0: Muy probablemente humano
                  - 0.5: Neutro
                  - 0.0: Muy probablemente bot

    Returns:
        dict: Respuesta de Google con score y otros datos

    Raises:
        HTTPException: Si el reCAPTCHA es inválido o el score es bajo
    """
    # Si no hay secret key configurada, saltamos la validación (solo desarrollo)
    if not settings.RECAPTCHA_SECRET_KEY:
        logger.warning("recaptcha.skipped_unconfigured")
        return {
            "success": True,
            "score": 1.0,
            "action": "submit",
            "challenge_ts": "",
            "hostname": "localhost",
            "warning": "reCAPTCHA deshabilitado - solo para desarrollo",
        }

    if not token:
        raise HTTPException(
            status_code=400, detail="Token de reCAPTCHA requerido pero no proporcionado"
        )

    url = "https://www.google.com/recaptcha/api/siteverify"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                data={"secret": settings.RECAPTCHA_SECRET_KEY, "response": token},
            )

        data = response.json()

        # Log para debug
        logger.info(
            "recaptcha.verified",
            extra={
                "success": data.get("success"),
                "score": data.get("score"),
                "action": data.get("action"),
            },
        )

        # Verificar si la respuesta fue exitosa
        if not data.get("success"):
            error_codes = data.get("error-codes", [])
            logger.warning(
                "recaptcha.invalid",
                extra={"error_codes": error_codes},
            )
            raise HTTPException(
                status_code=400,
                detail="reCAPTCHA inválido. Por favor intenta nuevamente.",
            )

        # Verificar el score
        score = data.get("score", 0.0)
        if score < min_score:
            logger.warning(
                "recaptcha.low_score",
                extra={"score": score, "min_score": min_score},
            )
            raise HTTPException(
                status_code=400,
                detail="Verificación de seguridad fallida. "
                "Por favor intenta nuevamente o contacta al administrador.",
            )

        return data

    except httpx.TimeoutException:
        logger.warning("recaptcha.timeout")
        raise HTTPException(
            status_code=503,
            detail="Servicio de verificación temporalmente no disponible. "
            "Por favor intenta más tarde.",
        )
    except httpx.RequestError as e:
        logger.warning(
            "recaptcha.network_error",
            extra={"error_type": type(e).__name__},
        )
        raise HTTPException(
            status_code=503,
            detail="Error al verificar reCAPTCHA. Por favor intenta más tarde.",
        )
    except HTTPException:
        # Re-raise HTTPException as-is
        raise
    except Exception:
        logger.exception("recaptcha.unexpected_error")
        raise HTTPException(
            status_code=500, detail="Error interno al verificar reCAPTCHA"
        )

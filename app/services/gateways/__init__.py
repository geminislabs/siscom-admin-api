# app/services/gateways/__init__.py
# Registro central de pasarelas de pago.
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from app.services.gateways.protocol import GatewayProvider

logger = logging.getLogger(__name__)

class GatewayRegistry:
    """
    Registro de pasarelas disponibles en runtime.
    Singleton — instanciado al final de este módulo.
    """

    def __init__(self) -> None:
        self._providers: dict[str, "GatewayProvider"] = {}

    def register(self, name: str, provider: "GatewayProvider") -> None:
        self._providers[name] = provider
        logger.info("Pasarela registrada: %s", name)

    def get(self, name: str) -> "GatewayProvider":
        provider = self._providers.get(name)
        if not provider:
            available = list(self._providers.keys())
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pasarela '{name}' no disponible. Disponibles: {available}",
            )
        return provider

    def get_default(self) -> "GatewayProvider":
        if not self._providers:
            raise HTTPException(503, "No hay pasarelas de pago configuradas")
        return next(iter(self._providers.values()))

    def get_default_name(self) -> str:
        if not self._providers:
            raise HTTPException(503, "No hay pasarelas configuradas")
        return next(iter(self._providers.keys()))

    def available(self) -> list[str]:
        return list(self._providers.keys())

registry = GatewayRegistry()


def initialize_gateways() -> None:
    """
    Registra las pasarelas configuradas según variables de entorno.
    Se llama desde el lifespan de FastAPI en app/main.py.
    """
    from app.core.config import settings

    if getattr(settings, "STRIPE_SECRET_KEY", None):
        try:
            from app.services.gateways.stripe_gateway import StripeGateway
            registry.register("stripe", StripeGateway())
        except Exception as e:
            logger.error("No se pudo inicializar Stripe: %s", e)

    registered = registry.available()
    if registered:
        logger.info("Pasarelas activas: %s", registered)
    else:
        logger.warning("ADVERTENCIA: No hay pasarelas de pago configuradas")

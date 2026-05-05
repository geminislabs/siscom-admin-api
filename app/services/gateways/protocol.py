# app/services/gateways/protocol.py

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy.orm import Session


@runtime_checkable
class GatewayProvider(Protocol):
    """
    Contrato de pasarela de pago.
    """

    def get_or_create_customer(
        self,
        db: Session,
        account_id: UUID,
        billing_email: str,
        account_name: str,
    ) -> str:
        """Devuelve el external_customer_id. Lo crea en la pasarela si no existe."""
        ...

    def create_setup_intent(
        self,
        db: Session,
        organization_id: UUID,
    ) -> dict:
        """Inicia el flujo de guardado de método de pago (sin cobrar)."""
        ...

    def create_payment_intent(
        self,
        db: Session,
        organization_id: UUID,
        plan_id: UUID,
        billing_cycle: str,
    ) -> dict:
        """
        Crea un intento de cobro.
        El monto SIEMPRE se calcula en backend desde la tabla plans.
        El frontend nunca envía el monto.
        """
        ...

    def list_payment_methods(
        self,
        db: Session,
        organization_id: UUID,
    ) -> list[dict]:
        """Lista métodos de pago guardados del account para esta pasarela."""
        ...

    def detach_payment_method(
        self,
        db: Session,
        organization_id: UUID,
        external_token: str,
    ) -> None:
        """
        Elimina un método de pago.
        Debe validar que el método pertenece al account (anti-IDOR).
        """
        ...

    def set_default_payment_method(
        self,
        db: Session,
        organization_id: UUID,
        external_token: str,
    ) -> None:
        """Establece un método de pago como predeterminado."""
        ...

    def handle_webhook(
        self,
        db: Session,
        payload: bytes,
        signature: str,
    ) -> None:
        """
        Verifica autenticidad del webhook y procesa el evento.
        Garantías requeridas:
          1. Verificar firma ANTES de leer el body
          2. Idempotencia: ignorar eventos ya procesados
          3. Siempre responder 200 (incluso en eventos ignorados)
        """
        ...

    def get_client_config(self) -> dict:
        """
        Configuración pública para inicializar el SDK en el frontend.
        Stripe   → { "gateway": "stripe", "publishable_key": "pk_..." }
        PayPal   → { "gateway": "paypal", "client_id": "..." }
        """
        ...

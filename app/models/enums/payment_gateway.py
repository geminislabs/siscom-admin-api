from __future__ import annotations

import enum


class PaymentGateway(str, enum.Enum):
    """
    Pasarelas soportadas.
    """

    STRIPE = "stripe"

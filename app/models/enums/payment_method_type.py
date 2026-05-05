from __future__ import annotations

import enum


class PaymentMethodType(str, enum.Enum):
    CARD = "card"
    OXXO = "oxxo"
    SPEI = "spei"
    BANK_TRANSFER = "bank_transfer"

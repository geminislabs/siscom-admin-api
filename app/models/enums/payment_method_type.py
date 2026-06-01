# app/models/enums/payment_method_type.py
from __future__ import annotations

import enum


class PaymentMethodType(str, enum.Enum):
    CARD            = "card"
    CASH_VOUCHER    = "cash_voucher"
    BANK_TRANSFER   = "bank_transfer"
    BANK_REDIRECT   = "bank_redirect"
    WALLET          = "wallet"
    INSTALLMENTS    = "installments"
    REAL_TIME       = "real_time"
    LOYALTY_POINTS  = "loyalty_points"
    GIFT_CARD       = "gift_card"
    CRYPTO          = "crypto"
    MANUAL          = "manual"

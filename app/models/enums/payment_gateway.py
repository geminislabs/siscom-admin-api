# app/models/enums/payment_gateway.py
from __future__ import annotations
import enum


class PaymentGateway(str, enum.Enum):
    STRIPE      = "stripe"
    CONEKTA     = "conekta"
    MERCADOPAGO = "mercadopago"
    PAYPAL      = "paypal"
    MANUAL      = "manual"
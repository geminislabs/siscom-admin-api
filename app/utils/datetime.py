from datetime import datetime, timedelta, timezone
from typing import Optional


def utcnow() -> datetime:
    """
    Devuelve el instante UTC actual como datetime *naive* (sin tzinfo).

    Equivalente a ``datetime.utcnow()`` pero sin el ``DeprecationWarning``
    introducido en Python 3.12. Se mantiene naive a propósito para preservar
    el comportamiento histórico de comparaciones, serialización y persistencia
    en columnas ``TIMESTAMP WITHOUT TIME ZONE`` del esquema actual.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def add_days(base_date: Optional[datetime] = None, days: int = 0) -> datetime:
    """
    Agrega días a una fecha base.
    Si no se proporciona fecha base, usa la fecha actual.
    """
    if base_date is None:
        base_date = utcnow()
    return base_date + timedelta(days=days)


def add_months(base_date: Optional[datetime] = None, months: int = 1) -> datetime:
    """
    Agrega meses a una fecha base (aproximado: 30 días por mes).
    Si no se proporciona fecha base, usa la fecha actual.
    """
    if base_date is None:
        base_date = utcnow()
    return base_date + timedelta(days=30 * months)


def add_years(base_date: Optional[datetime] = None, years: int = 1) -> datetime:
    """
    Agrega años a una fecha base (365 días por año).
    Si no se proporciona fecha base, usa la fecha actual.
    """
    if base_date is None:
        base_date = utcnow()
    return base_date + timedelta(days=365 * years)


def calculate_expiration(
    subscription_type: str, base_date: Optional[datetime] = None
) -> datetime:
    """
    Calcula la fecha de expiración según el tipo de suscripción.
    MONTHLY: 30 días
    YEARLY: 365 días
    """
    if base_date is None:
        base_date = utcnow()

    if subscription_type == "MONTHLY":
        return add_days(base_date, 30)
    elif subscription_type == "YEARLY":
        return add_days(base_date, 365)
    else:
        raise ValueError(f"Tipo de suscripción no válido: {subscription_type}")

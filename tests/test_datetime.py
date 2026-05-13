"""Tests para app.utils.datetime: deltas de suscripción y rutas con fecha explícita vs UTC now."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.utils.datetime import (
    add_days,
    add_months,
    add_years,
    calculate_expiration,
)

# Fecha ancla para comprobar aritmética sin depender del reloj del sistema.
BASE = datetime(2024, 3, 15, 14, 30, 0)


def test_add_days_applies_positive_delta():
    assert add_days(BASE, days=10) == BASE + timedelta(days=10)


def test_add_days_supports_negative_delta():
    assert add_days(BASE, days=-3) == BASE + timedelta(days=-3)


def test_add_days_zero_returns_same_instant():
    assert add_days(BASE, days=0) == BASE


def test_add_days_uses_utc_now_when_no_base():
    fixed = datetime(2024, 1, 1, 12, 0, 0)
    with patch("app.utils.datetime.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed
        assert add_days(days=7) == fixed + timedelta(days=7)


def test_add_months_uses_thirty_days_per_month():
    assert add_months(BASE, months=2) == BASE + timedelta(days=60)


def test_add_months_uses_utc_now_when_no_base():
    fixed = datetime(2024, 6, 1, 0, 0, 0)
    with patch("app.utils.datetime.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed
        assert add_months(months=1) == fixed + timedelta(days=30)


def test_add_years_uses_three_hundred_sixty_five_days_per_year():
    assert add_years(BASE, years=2) == BASE + timedelta(days=730)


def test_add_years_uses_utc_now_when_no_base():
    fixed = datetime(2023, 12, 31, 23, 59, 59)
    with patch("app.utils.datetime.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed
        assert add_years(years=1) == fixed + timedelta(days=365)


def test_calculate_expiration_monthly_equals_thirty_days_from_base():
    assert calculate_expiration("MONTHLY", BASE) == add_days(BASE, 30)


def test_calculate_expiration_yearly_equals_three_hundred_sixty_five_days_from_base():
    assert calculate_expiration("YEARLY", BASE) == add_days(BASE, 365)


def test_calculate_expiration_monthly_uses_utc_now_when_no_base():
    fixed = datetime(2025, 2, 1, 9, 0, 0)
    with patch("app.utils.datetime.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed
        assert calculate_expiration("MONTHLY") == fixed + timedelta(days=30)


def test_calculate_expiration_yearly_uses_utc_now_when_no_base():
    fixed = datetime(2025, 2, 1, 9, 0, 0)
    with patch("app.utils.datetime.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed
        assert calculate_expiration("YEARLY") == fixed + timedelta(days=365)


def test_calculate_expiration_rejects_unknown_subscription_type():
    with pytest.raises(ValueError) as exc_info:
        calculate_expiration("WEEKLY", BASE)
    msg = str(exc_info.value)
    assert "Tipo de suscripción no válido" in msg
    assert "WEEKLY" in msg

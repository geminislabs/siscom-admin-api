"""Tests para pagos manuales (cálculo de monto y reglas de unidades)."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.invoice import Invoice, InvoiceStatus
from app.models.plan import Plan
from app.services.manual_payment_service import (
    MIGRATE_MIN_UNITS,
    _next_invoice_number,
    _validate_migrate_units,
    calculate_manual_payment_amount,
)


def _plan(code: str, monthly: str = "100.00", yearly: str = "1080.00") -> Plan:
    return Plan(
        id=uuid4(),
        name=f"Plan {code}",
        code=code,
        price_monthly=Decimal(monthly),
        price_yearly=Decimal(yearly),
        is_active=True,
    )


def test_calculate_amount_monthly_single_unit():
    plan = _plan("trackgo", "299.00", "3229.20")
    assert calculate_manual_payment_amount(plan, "MONTHLY", 1) == Decimal("299.00")


def test_calculate_amount_yearly_multiple_units():
    plan = _plan("fleet", "50.00", "540.00")
    assert calculate_manual_payment_amount(plan, "YEARLY", 10) == Decimal("5400.00")


def test_migrate_plan_rejects_below_minimum():
    plan = _plan("nexus-core-migrate")
    with pytest.raises(HTTPException) as exc:
        _validate_migrate_units(plan, MIGRATE_MIN_UNITS - 1)
    assert exc.value.status_code == 400


def test_migrate_plan_accepts_minimum_units():
    plan = _plan("nexus-core-migrate")
    _validate_migrate_units(plan, MIGRATE_MIN_UNITS)


def test_next_invoice_number_is_globally_unique(
    db_session, test_account_data, test_organization_data
):
    year = datetime.now(timezone.utc).year
    db_session.add(
        Invoice(
            account_id=test_account_data.id,
            organization_id=test_organization_data.id,
            invoice_number=f"INV-{year}-0001",
            invoice_status=InvoiceStatus.PAID.value,
            subtotal=Decimal("100"),
            total_amount=Decimal("100"),
        )
    )
    db_session.commit()

    assert _next_invoice_number(db_session) == f"INV-{year}-0002"

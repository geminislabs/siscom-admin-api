"""Un pago exitoso levanta la suspensión por falta de pago (`suspension.reactivar_por_pago`).

GAC suspende con una causa: `non_payment` (por defecto) u `other`. El pago sólo
mira esa causa, y sólo reactiva lo que le toca:

- la cuenta y la organización suspendidas por falta de pago, sí;
- lo suspendido por otra causa, no;
- una subcuenta suspendida por su marca, sólo cuando paga la marca.

Los escenarios llegan por los endpoints de GAC, que son los que dejan la causa
en la auditoría, y el pago por el webhook real de Stripe.
"""

from uuid import uuid4

import pytest

from app.api.deps import AuthResult
from app.api.v1.endpoints.internal import accounts as accounts_endpoint
from app.api.v1.endpoints.internal import organizations as organizations_endpoint
from app.main import app
from app.models.account_event import AccountEvent
from app.models.payment import PaymentStatus
from app.services import suspension
from app.services.gateways.stripe_gateway import StripeGateway
from tests.test_stripe_payments import (
    _feed_events,
    _invoice_payment,
    _plan,
    _succeeded_event,
)
from tests.test_suspension import _cuenta, _organizacion, _suspender


def _gac():
    return AuthResult(
        auth_type="paseto",
        payload={"service": "gac", "role": "GAC_ADMIN", "internal_id": "gac-1"},
        service="gac",
        role="GAC_ADMIN",
    )


@pytest.fixture
def gac(client):
    app.dependency_overrides[accounts_endpoint.get_auth_for_internal_accounts] = _gac
    app.dependency_overrides[
        organizations_endpoint.get_auth_for_internal_organizations
    ] = _gac
    return client


def _suspender_cuenta(gac, cuenta, **cuerpo):
    respuesta = gac.patch(
        f"/api/v1/internal/accounts/{cuenta.id}/status",
        json={"status": "SUSPENDED", **cuerpo},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta


def _suspender_org(gac, org, **params):
    respuesta = gac.patch(
        f"/api/v1/internal/organizations/{org.id}/status",
        params={"new_status": "SUSPENDED", **params},
    )
    assert respuesta.status_code == 200, respuesta.text
    return respuesta


def _pagar(db, cuenta, org, monkeypatch):
    """Un pago exitoso de `org`, por el webhook de Stripe."""
    plan = _plan(db)
    _, payment = _invoice_payment(
        db,
        cuenta,
        org,
        plan,
        pi_id=f"pi_{uuid4().hex[:8]}",
        status=PaymentStatus.PENDING.value,
    )
    _feed_events(
        monkeypatch, _succeeded_event(payment, org, plan, f"evt_{uuid4().hex[:8]}")
    )
    StripeGateway().handle_webhook(db, b"{}", "sig")
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.SUCCESS.value
    return payment


def _estados(db, *objetos):
    for o in objetos:
        db.refresh(o)
    return [getattr(o.status, "value", o.status) for o in objetos]


# ---------------------------------------------------------------------------
# La causa queda en la auditoría
# ---------------------------------------------------------------------------


def test_suspender_una_cuenta_guarda_la_causa(gac, db_session):
    cuenta = _cuenta(db_session)
    _suspender_cuenta(gac, cuenta, cause="other")

    evento = (
        db_session.query(AccountEvent).filter(AccountEvent.target_id == cuenta.id).one()
    )
    assert evento.event_metadata["cause"] == "other"


def test_la_causa_por_defecto_es_falta_de_pago(gac, db_session):
    cuenta = _cuenta(db_session)
    _suspender_cuenta(gac, cuenta)

    evento = (
        db_session.query(AccountEvent).filter(AccountEvent.target_id == cuenta.id).one()
    )
    assert evento.event_metadata["cause"] == "non_payment"


def test_suspender_una_organizacion_ahora_se_audita(gac, db_session):
    cuenta = _cuenta(db_session)
    org = _organizacion(db_session, cuenta)
    _suspender_org(gac, org, cause="other")

    evento = (
        db_session.query(AccountEvent).filter(AccountEvent.target_id == org.id).one()
    )
    assert evento.event_type == "org_status_changed"
    assert evento.event_metadata["anterior"] == "ACTIVE"
    assert evento.event_metadata["nuevo"] == "SUSPENDED"
    assert evento.event_metadata["cause"] == "other"
    assert evento.event_metadata["gac_user"] == "gac-1"

    # Repetir el mismo estado no deja otro evento.
    _suspender_org(gac, org)
    assert (
        db_session.query(AccountEvent).filter(AccountEvent.target_id == org.id).count()
        == 1
    )


# ---------------------------------------------------------------------------
# El pago
# ---------------------------------------------------------------------------


def test_pagar_reactiva_la_cuenta_suspendida_por_falta_de_pago(
    gac, db_session, monkeypatch
):
    cuenta = _cuenta(db_session)
    org = _organizacion(db_session, cuenta)
    _suspender_cuenta(gac, cuenta)

    payment = _pagar(db_session, cuenta, org, monkeypatch)

    assert _estados(db_session, cuenta) == ["ACTIVE"]
    assert suspension.bloqueo_de(db_session, org.id) is None
    evento = (
        db_session.query(AccountEvent)
        .filter(
            AccountEvent.target_id == cuenta.id,
            AccountEvent.event_metadata["nuevo"].astext == "ACTIVE",
        )
        .one()
    )
    assert evento.actor_type == "system"
    assert evento.event_metadata["reason"] == "payment"
    assert evento.event_metadata["payment_id"] == str(payment.id)


def test_pagar_reactiva_la_organizacion_suspendida_por_falta_de_pago(
    gac, db_session, monkeypatch
):
    cuenta = _cuenta(db_session)
    org = _organizacion(db_session, cuenta)
    _suspender_org(gac, org)

    _pagar(db_session, cuenta, org, monkeypatch)

    assert _estados(db_session, org) == ["ACTIVE"]


@pytest.mark.parametrize("que", ["cuenta", "organizacion"])
def test_pagar_no_levanta_una_suspension_por_otra_causa(
    gac, db_session, monkeypatch, que
):
    cuenta = _cuenta(db_session)
    org = _organizacion(db_session, cuenta)
    if que == "cuenta":
        _suspender_cuenta(gac, cuenta, cause="other")
    else:
        _suspender_org(gac, org, cause="other")

    _pagar(db_session, cuenta, org, monkeypatch)

    assert _estados(db_session, cuenta if que == "cuenta" else org) == ["SUSPENDED"]


def test_sin_registro_se_trata_como_falta_de_pago(db_session, monkeypatch):
    """Lo suspendido antes de que hubiera causa (o a mano en la base)."""
    cuenta = _cuenta(db_session)
    org = _organizacion(db_session, cuenta)
    _suspender(db_session, cuenta)

    _pagar(db_session, cuenta, org, monkeypatch)

    assert _estados(db_session, cuenta) == ["ACTIVE"]


def test_la_marca_paga_por_sus_subcuentas(gac, db_session, monkeypatch):
    marca = _cuenta(db_session, "Marca", tipo="RESELLER")
    org_marca = _organizacion(db_session, marca)
    por_la_marca = _cuenta(db_session, "Por la marca", padre=marca)
    por_su_cuenta = _cuenta(db_session, "Por su cuenta", padre=marca)
    # Ésta se suspendió sola antes, por su propia deuda: la marca no la paga.
    _suspender_cuenta(gac, por_su_cuenta)
    _suspender_cuenta(gac, marca, include_subaccounts=True)

    _pagar(db_session, marca, org_marca, monkeypatch)

    assert _estados(db_session, marca, por_la_marca, por_su_cuenta) == [
        "ACTIVE",
        "ACTIVE",
        "SUSPENDED",
    ]


def test_la_subcuenta_no_se_reactiva_pagando_la_deuda_de_su_marca(
    gac, db_session, monkeypatch
):
    marca = _cuenta(db_session, "Marca", tipo="RESELLER")
    cliente = _cuenta(db_session, "Cliente", padre=marca)
    org_cliente = _organizacion(db_session, cliente)
    _suspender_cuenta(gac, marca, include_subaccounts=True)

    _pagar(db_session, cliente, org_cliente, monkeypatch)

    assert _estados(db_session, marca, cliente) == ["SUSPENDED", "SUSPENDED"]


def test_pagar_una_organizacion_activa_no_registra_nada(db_session, monkeypatch):
    cuenta = _cuenta(db_session)
    org = _organizacion(db_session, cuenta)

    _pagar(db_session, cuenta, org, monkeypatch)

    assert (
        db_session.query(AccountEvent)
        .filter(AccountEvent.target_id.in_([cuenta.id, org.id]))
        .count()
        == 0
    )


def test_borrada_no_se_reactiva(db_session, monkeypatch):
    cuenta = _cuenta(db_session)
    org = _organizacion(db_session, cuenta)
    _suspender(db_session, cuenta, "DELETED")

    assert suspension.reactivar_por_pago(db_session, org.id) == []
    assert _estados(db_session, cuenta) == ["DELETED"]

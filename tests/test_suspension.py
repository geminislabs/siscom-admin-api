"""Suspensión de organizaciones y cuentas (`app/services/suspension.py`).

La regla se prueba por HTTP con la validación real de `_load_current_user`:
sólo se sustituye la verificación del token de Cognito (`get_current_user`).
Los escenarios son los que se acordaron al diseñarla:

- la organización suspendida, o su cuenta, cierra todo menos facturación
  para quien la administra y lo personal (`/auth/me`, `/users/me`…);
- la regla mira la organización en la que se actúa, no a la persona: el
  invitado de una organización ajena sigue entrando en ella aunque la suya
  esté suspendida;
- suspender una marca no suspende a sus clientes;
- borrada no deja pasar a nadie.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.api import deps as deps_mod
from app.api.deps import AuthResult, get_current_user
from app.api.v1.endpoints.internal import accounts as accounts_endpoint
from app.main import app
from app.models.account import Account
from app.models.account_event import AccountEvent
from app.models.organization import Organization
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.unit import Unit
from app.models.user import User
from app.services import session_revocation
from app.services.scope_store import ScopePurpose
from tests.conftest import _GrabadorDeRevocaciones

AUTH = {"Authorization": "Bearer irrelevante"}


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------


def _cuenta(db, nombre="Cuenta", *, padre=None, tipo="CUSTOMER", estado="ACTIVE"):
    cid = uuid4()
    cuenta = Account(
        id=cid,
        name=nombre,
        status=estado,
        account_type=tipo,
        parent_account_id=padre.id if padre is not None else None,
        account_path=[*padre.account_path, cid] if padre is not None else [cid],
    )
    db.add(cuenta)
    db.commit()
    return cuenta


def _organizacion(db, cuenta, estado="ACTIVE"):
    org = Organization(id=uuid4(), name=f"Org {uuid4().hex[:6]}", account_id=cuenta.id)
    org.status = estado
    db.add(org)
    db.commit()
    return org


def _persona(db, organizacion, rol=OrganizationRole.OWNER):
    user = User(
        id=uuid4(),
        default_organization_id=organizacion.id,
        cognito_sub=f"sub-{uuid4()}",
        email=f"{uuid4().hex[:8]}@example.com",
        full_name="Persona",
        is_master=False,
    )
    db.add(user)
    db.flush()
    _miembro_de(db, organizacion, user, rol)
    return user


def _miembro_de(db, organizacion, user, rol=OrganizationRole.MEMBER):
    db.add(
        OrganizationUser(
            organization_id=organizacion.id, user_id=user.id, role=rol.value
        )
    )
    db.commit()


def _como(user):
    app.dependency_overrides[get_current_user] = lambda: {"sub": user.cognito_sub}


def _suspender(db, obj, estado="SUSPENDED"):
    obj.status = estado
    db.commit()


@pytest.fixture
def escena(db_session):
    cuenta = _cuenta(db_session)
    org = _organizacion(db_session, cuenta)
    return SimpleNamespace(
        cuenta=cuenta,
        org=org,
        owner=_persona(db_session, org, OrganizationRole.OWNER),
        billing=_persona(db_session, org, OrganizationRole.BILLING),
        member=_persona(db_session, org, OrganizationRole.MEMBER),
    )


# ---------------------------------------------------------------------------
# La regla
# ---------------------------------------------------------------------------


def test_activa_da_acceso(client, escena):
    _como(escena.member)
    assert client.get("/api/v1/units", headers=AUTH).status_code == 200


@pytest.mark.parametrize("quien", ["organizacion", "cuenta"])
def test_suspendida_cierra_los_datos_con_el_motivo(client, db_session, escena, quien):
    _suspender(db_session, escena.org if quien == "organizacion" else escena.cuenta)

    _como(escena.owner)
    respuesta = client.get("/api/v1/units", headers=AUTH)

    assert respuesta.status_code == status.HTTP_403_FORBIDDEN
    cuerpo = respuesta.json()
    assert cuerpo["error_code"] == "organization_suspended"
    assert cuerpo["suspended_by"] == (
        "organization" if quien == "organizacion" else "account"
    )
    assert cuerpo["organization_id"] == str(escena.org.id)
    assert cuerpo["can_manage_billing"] is True
    # Los clientes ya publicados muestran `detail`: sigue siendo texto.
    assert isinstance(cuerpo["detail"], str) and cuerpo["detail"]


def test_un_member_no_puede_administrar_la_facturacion(client, db_session, escena):
    _suspender(db_session, escena.org)
    _como(escena.member)

    respuesta = client.get("/api/v1/units", headers=AUTH)
    assert respuesta.json()["can_manage_billing"] is False
    assert client.get("/api/v1/subscriptions", headers=AUTH).status_code == 403


@pytest.mark.parametrize("rol", ["owner", "billing"])
def test_quien_administra_la_facturacion_puede_pagar(client, db_session, escena, rol):
    _suspender(db_session, escena.cuenta)
    _como(getattr(escena, rol))

    assert client.get("/api/v1/subscriptions", headers=AUTH).status_code == 200
    assert client.get("/api/v1/units", headers=AUTH).status_code == 403


def test_borrada_no_deja_pasar_ni_a_facturacion(client, db_session, escena):
    _suspender(db_session, escena.org, "DELETED")
    _como(escena.owner)

    respuesta = client.get("/api/v1/subscriptions", headers=AUTH)
    assert respuesta.status_code == 403
    assert respuesta.json()["error_code"] == "organization_deleted"
    assert respuesta.json()["can_manage_billing"] is False


def test_el_invitado_sigue_entrando_a_la_organizacion_ajena(client, db_session, escena):
    """Escenario 1: su cuenta está suspendida, pero la organización a la que lo
    invitaron no. Ve esa, y no la suya."""
    ajena = _organizacion(db_session, _cuenta(db_session, "Ajena"))
    _miembro_de(db_session, ajena, escena.owner)
    _suspender(db_session, escena.cuenta)
    _como(escena.owner)

    en_la_ajena = {**AUTH, "X-Organization-Id": str(ajena.id)}
    assert client.get("/api/v1/units", headers=en_la_ajena).status_code == 200
    assert client.get("/api/v1/units", headers=AUTH).status_code == 403


def test_el_invitado_de_una_organizacion_suspendida_sigue_en_la_suya(
    client, db_session, escena
):
    propia = _organizacion(db_session, _cuenta(db_session, "Propia"))
    invitado = _persona(db_session, propia)
    _miembro_de(db_session, escena.org, invitado)
    _suspender(db_session, escena.cuenta)
    _como(invitado)

    assert client.get("/api/v1/units", headers=AUTH).status_code == 200
    en_la_suspendida = {**AUTH, "X-Organization-Id": str(escena.org.id)}
    assert client.get("/api/v1/units", headers=en_la_suspendida).status_code == 403


def test_suspender_una_marca_no_suspende_a_sus_clientes(client, db_session):
    marca = _cuenta(db_session, "Marca", tipo="RESELLER")
    cliente = _cuenta(db_session, "Cliente", padre=marca)
    org = _organizacion(db_session, cliente)
    persona = _persona(db_session, org)
    _suspender(db_session, marca)
    _como(persona)

    assert client.get("/api/v1/units", headers=AUTH).status_code == 200


def test_sin_membresia_sigue_siendo_el_403_de_siempre(client, db_session, escena):
    """La suspensión no adelanta a la membresía: a quien no es miembro no se le
    cuenta el estado de una organización ajena."""
    _suspender(db_session, escena.org)
    _como(escena.member)
    ajena = _organizacion(db_session, _cuenta(db_session, "Ajena"), "SUSPENDED")

    respuesta = client.get(
        "/api/v1/units", headers={**AUTH, "X-Organization-Id": str(ajena.id)}
    )
    assert respuesta.status_code == 403
    assert "error_code" not in respuesta.json()


# ---------------------------------------------------------------------------
# Lo que sigue abierto
# ---------------------------------------------------------------------------


def test_auth_me_contesta_y_cuenta_el_motivo(client, db_session, escena):
    _como(escena.member)
    assert client.get("/api/v1/auth/me", headers=AUTH).json()["access_blocked"] is None

    _suspender(db_session, escena.cuenta)
    respuesta = client.get("/api/v1/auth/me", headers=AUTH)

    assert respuesta.status_code == 200
    assert respuesta.json()["access_blocked"] == {
        "error_code": "organization_suspended",
        "suspended_by": "account",
        "can_manage_billing": False,
    }


def test_lo_personal_sigue_abierto(client, db_session, escena):
    _suspender(db_session, escena.org)
    _como(escena.member)

    assert client.get("/api/v1/users/me", headers=AUTH).status_code == 200
    assert client.get("/api/v1/mobility/devices", headers=AUTH).status_code == 200


def test_el_selector_marca_las_organizaciones_suspendidas(client, db_session, escena):
    otra = _organizacion(db_session, _cuenta(db_session, "Otra"))
    _miembro_de(db_session, otra, escena.owner, OrganizationRole.MEMBER)
    _suspender(db_session, escena.org)
    _como(escena.owner)

    filas = {
        f["organization_id"]: f["access_blocked"]
        for f in client.get("/api/v1/auth/organizations", headers=AUTH).json()
    }
    assert filas[str(otra.id)] is None
    assert filas[str(escena.org.id)] == {
        "error_code": "organization_suspended",
        "suspended_by": "organization",
        "can_manage_billing": True,
    }


def test_el_login_no_emite_data_token_en_una_organizacion_suspendida(
    db_session, escena
):
    from app.api.v1.endpoints.auth import _try_issue_data_token

    _suspender(db_session, escena.org)

    # Sin issuer ni store: si intentara emitir, reventaría.
    assert _try_issue_data_token(db_session, escena.owner, None, None) is None


# ---------------------------------------------------------------------------
# Los caminos que no pasan por `_load_current_user`
# ---------------------------------------------------------------------------


@pytest.fixture
def cognito_de(monkeypatch):
    def _fijar(user):
        monkeypatch.setattr(
            deps_mod, "verify_cognito_token", lambda t: {"sub": user.cognito_sub}
        )

    return _fijar


CREDENCIALES = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")


def test_require_organization_permission_cierra(
    db_session, escena, cognito_de, monkeypatch
):
    monkeypatch.setattr("app.services.permisos.tiene_permiso", lambda *a: True)
    _suspender(db_session, escena.org)
    cognito_de(escena.owner)

    with pytest.raises(HTTPException) as ei:
        deps_mod.require_organization_permission("x")(
            credentials=CREDENCIALES, db=db_session
        )
    assert ei.value.error_code == "organization_suspended"

    facturacion = deps_mod.require_organization_permission(
        "x", suspension=deps_mod.SuspensionFacturacion
    )
    assert facturacion(credentials=CREDENCIALES, db=db_session).user_id == (
        escena.owner.id
    )


def test_require_capability_cierra(db_session, escena, cognito_de):
    _suspender(db_session, escena.cuenta)
    cognito_de(escena.owner)

    with pytest.raises(HTTPException) as ei:
        deps_mod.require_capability("ai_features")(
            credentials=CREDENCIALES, db=db_session
        )
    assert ei.value.error_code == "organization_suspended"


def test_cognito_or_paseto_cierra_a_cognito(db_session, escena, cognito_de):
    _suspender(db_session, escena.org)
    cognito_de(escena.member)

    with pytest.raises(HTTPException) as ei:
        deps_mod.get_auth_cognito_or_paseto()(credentials=CREDENCIALES, db=db_session)
    assert ei.value.error_code == "organization_suspended"


def test_lo_comercial_de_una_cuenta_suspendida_tampoco(db_session, escena, monkeypatch):
    monkeypatch.setattr("app.services.permisos.tiene_permiso", lambda *a: True)
    _suspender(db_session, escena.cuenta)

    with pytest.raises(HTTPException) as ei:
        deps_mod.require_account_permission("branding.write")(
            account_id=escena.cuenta.id,
            db=db_session,
            current_user={"sub": escena.owner.cognito_sub},
        )
    assert ei.value.status_code == 403


# ---------------------------------------------------------------------------
# Revocación al suspender
# ---------------------------------------------------------------------------


class _Grabador(list):
    def revoke_all_for_subject(self, subject_id, purpose=ScopePurpose.SESSION):
        self.append((subject_id, purpose))
        return []


@pytest.fixture
def grabador():
    g = _Grabador()
    session_revocation.usar_store(lambda: g)
    yield g
    session_revocation.usar_store(_GrabadorDeRevocaciones)


@pytest.mark.parametrize("quien", ["organizacion", "cuenta"])
def test_suspender_revoca_sesiones_y_enlaces(db_session, escena, grabador, quien):
    unidad = Unit(id=uuid4(), organization_id=escena.org.id, name="U1")
    db_session.add(unidad)
    db_session.commit()
    grabador.clear()

    _suspender(db_session, escena.org if quien == "organizacion" else escena.cuenta)

    sesiones = {s for s, p in grabador if p == ScopePurpose.SESSION}
    enlaces = {s for s, p in grabador if p == ScopePurpose.SHARE}
    assert sesiones == {escena.owner.id, escena.billing.id, escena.member.id}
    assert enlaces == {unidad.id}


def test_reactivar_no_revoca(db_session, escena, grabador):
    _suspender(db_session, escena.org)
    grabador.clear()

    _suspender(db_session, escena.org, "ACTIVE")

    assert grabador == []


# ---------------------------------------------------------------------------
# PATCH /internal/accounts/{id}/status
# ---------------------------------------------------------------------------


@pytest.fixture
def gac(client):
    app.dependency_overrides[accounts_endpoint.get_auth_for_internal_accounts] = (
        lambda: AuthResult(
            auth_type="paseto",
            payload={"service": "gac", "role": "GAC_ADMIN", "internal_id": "gac-1"},
            service="gac",
            role="GAC_ADMIN",
        )
    )
    return client


def _estado(gac, cuenta, **cuerpo):
    return gac.patch(f"/api/v1/internal/accounts/{cuenta.id}/status", json=cuerpo)


def test_suspender_y_reactivar_una_cuenta(gac, db_session, escena):
    respuesta = _estado(gac, escena.cuenta, status="SUSPENDED", reason="Falta de pago")

    assert respuesta.status_code == 200
    assert respuesta.json()["changed"] is True
    assert respuesta.json()["account"]["previous_status"] == "ACTIVE"
    db_session.refresh(escena.cuenta)
    assert escena.cuenta.status == "SUSPENDED"

    evento = (
        db_session.query(AccountEvent)
        .filter(
            AccountEvent.account_id == escena.cuenta.id,
            AccountEvent.event_type == "account_status_changed",
        )
        .one()
    )
    assert evento.event_metadata["reason"] == "Falta de pago"
    assert evento.event_metadata["gac_user"] == "gac-1"

    # Repetirlo no es error, sólo no cambia nada.
    assert _estado(gac, escena.cuenta, status="SUSPENDED").json()["changed"] is False

    assert _estado(gac, escena.cuenta, status="ACTIVE").json()["changed"] is True
    db_session.refresh(escena.cuenta)
    assert escena.cuenta.status == "ACTIVE"


def test_una_marca_arrastra_a_sus_subcuentas_solo_si_se_pide(gac, db_session):
    marca = _cuenta(db_session, "Marca", tipo="RESELLER")
    hija = _cuenta(db_session, "Hija", padre=marca, tipo="RESELLER")
    nieta = _cuenta(db_session, "Nieta", padre=hija)
    borrada = _cuenta(db_session, "Borrada", padre=marca, estado="DELETED")
    ajena = _cuenta(db_session, "Ajena")

    _estado(gac, marca, status="SUSPENDED")
    for c in (hija, nieta):
        db_session.refresh(c)
        assert c.status == "ACTIVE"

    respuesta = _estado(gac, marca, status="SUSPENDED", include_subaccounts=True)

    assert respuesta.status_code == 200
    assert respuesta.json()["changed"] is False
    assert {s["id"] for s in respuesta.json()["subaccounts"]} == {
        str(hija.id),
        str(nieta.id),
    }
    for c, esperado in ((hija, "SUSPENDED"), (nieta, "SUSPENDED")):
        db_session.refresh(c)
        assert c.status == esperado
    for c, esperado in ((borrada, "DELETED"), (ajena, "ACTIVE")):
        db_session.refresh(c)
        assert c.status == esperado

    listado = gac.get(f"/api/v1/internal/accounts/{marca.id}/subaccounts").json()
    assert [f["account_name"] for f in listado] == ["Borrada", "Hija", "Nieta"]


def test_include_subaccounts_solo_para_una_marca(gac, escena):
    respuesta = _estado(
        gac, escena.cuenta, status="SUSPENDED", include_subaccounts=True
    )
    assert respuesta.status_code == 422


def test_una_cuenta_borrada_no_se_toca(gac, db_session, escena):
    _suspender(db_session, escena.cuenta, "DELETED")
    assert _estado(gac, escena.cuenta, status="ACTIVE").status_code == 409


def test_borrar_no_se_hace_aqui(gac, escena):
    assert _estado(gac, escena.cuenta, status="DELETED").status_code == 422


def test_cuenta_inexistente(gac):
    respuesta = gac.patch(
        f"/api/v1/internal/accounts/{uuid4()}/status", json={"status": "SUSPENDED"}
    )
    assert respuesta.status_code == 404

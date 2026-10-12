"""Los endpoints con los que GAC convierte una cuenta en marca (B4, rebanada 4).

Entran por HTTP con tokens PASETO **reales** firmados con la clave de los
tests, no con un override de la dependencia: lo que se prueba es la puerta.
Los 403 se prueban con credenciales válidas de otra clase —un token de persona
de Nexus que Cognito aceptaría, un token de servicio de otro servicio—, porque
un test que solo prueba la ausencia de credencial no prueba la autorización.

La base sale de `create_all()`: sin los triggers de la 027, `account_path` lo
escribe el fixture.
"""

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import status

from app.models.account import Account
from app.models.account_event import AccountEvent
from app.models.capability import AccountCapability, Capability
from app.models.organization import Organization
from app.models.user import User
from app.services import account_capabilities
from app.utils.datetime import utcnow
from app.utils.paseto_token import generate_service_token

GAC_USER = "5f1d1c0e-0000-4000-8000-00000000cafe"


def _gac(**claims):
    token, _ = generate_service_token(
        "gac", "GAC_ADMIN", additional_claims={"internal_id": GAC_USER, **claims}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def catalogo(db_session):
    """Las cuatro capabilities comerciales que siembra la 027."""
    filas = {}
    for code, tipo in (
        ("white_label_enabled", "bool"),
        ("max_custom_domains", "int"),
        ("max_sub_accounts", "int"),
        ("can_resell", "bool"),
    ):
        cap = Capability(code=code, description=code, value_type=tipo)
        db_session.add(cap)
        filas[code] = cap
    # Una operativa: no se puede escribir a nivel cuenta.
    db_session.add(Capability(code="max_devices", description="op", value_type="int"))
    db_session.commit()
    return filas


def _cuenta(db_session, nombre, *, padre=None, tipo="CUSTOMER"):
    cid = uuid.uuid4()
    cuenta = Account(
        id=cid,
        name=nombre,
        status="ACTIVE",
        account_type=tipo,
        parent_account_id=padre.id if padre is not None else None,
        account_path=[*padre.account_path, cid] if padre is not None else [cid],
    )
    db_session.add(cuenta)
    db_session.commit()
    return cuenta


def _eventos(db_session, cuenta):
    return (
        db_session.query(AccountEvent)
        .filter(AccountEvent.account_id == cuenta.id)
        .order_by(AccountEvent.event_type)
        .all()
    )


def _fila(db_session, cuenta, cap):
    return (
        db_session.query(AccountCapability)
        .filter(
            AccountCapability.account_id == cuenta.id,
            AccountCapability.capability_id == cap.id,
        )
        .first()
    )


# =============================================================================
# La puerta
# =============================================================================


RUTAS = [
    ("patch", "/api/v1/internal/accounts/{id}", {"account_type": "RESELLER"}),
    ("get", "/api/v1/internal/accounts/{id}/capabilities", None),
    (
        "put",
        "/api/v1/internal/accounts/{id}/capabilities/white_label_enabled",
        {"value": True},
    ),
    ("delete", "/api/v1/internal/accounts/{id}/capabilities/white_label_enabled", None),
]


@pytest.mark.parametrize("metodo,ruta,cuerpo", RUTAS)
def test_un_token_de_persona_valido_no_entra(
    client, db_session, catalogo, metodo, ruta, cuerpo
):
    """El agujero de v1.36.0: Cognito válido y usuario existente, igual 403."""
    cuenta = _cuenta(db_session, "Gmail de Jesús")
    org = Organization(
        id=uuid.uuid4(), account_id=cuenta.id, name="Org", status="ACTIVE"
    )
    db_session.add(org)
    db_session.flush()
    persona = User(
        id=uuid.uuid4(),
        default_organization_id=org.id,
        cognito_sub="sub-persona",
        external_id="persona",
        email="persona@gmail.com",
        full_name="Persona",
        is_master=True,
    )
    db_session.add(persona)
    db_session.commit()

    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": "sub-persona"}
    ):
        kwargs = {"headers": {"Authorization": "Bearer token-de-cognito"}}
        if cuerpo is not None:
            kwargs["json"] = cuerpo
        r = getattr(client, metodo)(ruta.format(id=cuenta.id), **kwargs)

    assert r.status_code == status.HTTP_403_FORBIDDEN
    db_session.refresh(cuenta)
    assert cuenta.account_type == "CUSTOMER"
    assert _eventos(db_session, cuenta) == []


@pytest.mark.parametrize("metodo,ruta,cuerpo", RUTAS)
def test_un_token_de_otro_servicio_no_entra(
    client, db_session, catalogo, metodo, ruta, cuerpo
):
    cuenta = _cuenta(db_session, "Gmail de Jesús")
    token, _ = generate_service_token("nexus", "GAC_ADMIN")
    kwargs = {"headers": {"Authorization": f"Bearer {token}"}}
    if cuerpo is not None:
        kwargs["json"] = cuerpo
    r = getattr(client, metodo)(ruta.format(id=cuenta.id), **kwargs)
    assert r.status_code == status.HTTP_403_FORBIDDEN


def test_sin_credencial_no_entra(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Gmail de Jesús")
    r = client.patch(
        f"/api/v1/internal/accounts/{cuenta.id}", json={"account_type": "RESELLER"}
    )
    assert r.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


# =============================================================================
# PATCH: el tipo de cuenta
# =============================================================================


def test_convierte_una_cuenta_en_marca_y_lo_audita(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Gmail de Jesús")

    r = client.patch(
        f"/api/v1/internal/accounts/{cuenta.id}",
        json={"account_type": "RESELLER"},
        headers=_gac(),
    )

    assert r.status_code == status.HTTP_200_OK, r.text
    assert r.json() == {
        "id": str(cuenta.id),
        "account_name": "Gmail de Jesús",
        "account_type": "RESELLER",
        "parent_account_id": None,
        "changed": True,
    }
    db_session.refresh(cuenta)
    assert cuenta.account_type == "RESELLER"

    [evento] = _eventos(db_session, cuenta)
    assert evento.event_type == "account_updated"
    assert evento.actor_type == "service"
    assert evento.actor_user_id is None
    assert evento.event_metadata == {
        "campo": "account_type",
        "anterior": "CUSTOMER",
        "nuevo": "RESELLER",
        "service": "gac",
        "gac_user": GAC_USER,
    }


def test_repetir_el_mismo_tipo_no_audita(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Marca", tipo="RESELLER")
    r = client.patch(
        f"/api/v1/internal/accounts/{cuenta.id}",
        json={"account_type": "RESELLER"},
        headers=_gac(),
    )
    assert r.status_code == status.HTTP_200_OK
    assert r.json()["changed"] is False
    assert _eventos(db_session, cuenta) == []


def test_la_plataforma_no_cambia_de_tipo(client, db_session, catalogo):
    geminis = _cuenta(db_session, "Geminis", tipo="PLATFORM")
    r = client.patch(
        f"/api/v1/internal/accounts/{geminis.id}",
        json={"account_type": "CUSTOMER"},
        headers=_gac(),
    )
    assert r.status_code == status.HTTP_409_CONFLICT
    db_session.refresh(geminis)
    assert geminis.account_type == "PLATFORM"


def test_platform_no_se_asigna_por_api(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Cualquiera")
    r = client.patch(
        f"/api/v1/internal/accounts/{cuenta.id}",
        json={"account_type": "PLATFORM"},
        headers=_gac(),
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_campos_desconocidos_se_rechazan(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Cualquiera")
    r = client.patch(
        f"/api/v1/internal/accounts/{cuenta.id}",
        json={"account_type": "RESELLER", "parent_account_id": str(uuid.uuid4())},
        headers=_gac(),
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_no_regresa_a_cliente_con_subcuentas_vivas(client, db_session, catalogo):
    marca = _cuenta(db_session, "Marca", tipo="RESELLER")
    _cuenta(db_session, "Cliente de la marca", padre=marca)

    r = client.patch(
        f"/api/v1/internal/accounts/{marca.id}",
        json={"account_type": "CUSTOMER"},
        headers=_gac(),
    )

    assert r.status_code == status.HTTP_409_CONFLICT
    assert "1 subcuenta" in r.json()["detail"]
    db_session.refresh(marca)
    assert marca.account_type == "RESELLER"


def test_regresa_a_cliente_si_sus_hijas_estan_borradas(client, db_session, catalogo):
    marca = _cuenta(db_session, "Marca", tipo="RESELLER")
    hija = _cuenta(db_session, "Borrada", padre=marca)
    hija.status = "DELETED"
    db_session.commit()

    r = client.patch(
        f"/api/v1/internal/accounts/{marca.id}",
        json={"account_type": "CUSTOMER"},
        headers=_gac(),
    )
    assert r.status_code == status.HTTP_200_OK
    assert r.json()["account_type"] == "CUSTOMER"


def test_cuenta_inexistente_es_404(client, db_session, catalogo):
    r = client.patch(
        f"/api/v1/internal/accounts/{uuid.uuid4()}",
        json={"account_type": "RESELLER"},
        headers=_gac(),
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# Capabilities
# =============================================================================


def test_lista_las_comerciales_con_su_valor_efectivo(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Sin nada")
    r = client.get(
        f"/api/v1/internal/accounts/{cuenta.id}/capabilities", headers=_gac()
    )
    assert r.status_code == status.HTTP_200_OK
    filas = {f["code"]: f for f in r.json()}
    # Solo las comerciales; max_devices es operativa.
    assert set(filas) == set(account_capabilities.DEFAULT_ACCOUNT_CAPABILITIES)
    assert filas["white_label_enabled"] == {
        "code": "white_label_enabled",
        "value_type": "bool",
        "description": "white_label_enabled",
        "own_value": None,
        "reason": None,
        "expires_at": None,
        "expired": False,
        "effective_value": False,
        "source": "default",
        "limited_by": None,
    }


def test_activa_la_marca_propia_y_lo_audita(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Gmail de Jesús", tipo="RESELLER")

    r = client.put(
        f"/api/v1/internal/accounts/{cuenta.id}/capabilities/white_label_enabled",
        json={"value": True, "reason": "Prueba de B4"},
        headers=_gac(),
    )

    assert r.status_code == status.HTTP_200_OK, r.text
    cuerpo = r.json()
    assert cuerpo["own_value"] is True
    assert cuerpo["effective_value"] is True
    assert cuerpo["source"] == "cuenta"
    assert account_capabilities.puede(db_session, cuenta.id, "white_label_enabled")

    fila = _fila(db_session, cuenta, catalogo["white_label_enabled"])
    assert (fila.value_bool, fila.value_int, fila.value_text) == (True, None, None)
    assert fila.reason == "Prueba de B4"

    [evento] = _eventos(db_session, cuenta)
    assert evento.event_type == "account_capability_set"
    assert evento.target_type == "account_capability"
    assert evento.target_id == fila.id
    assert evento.event_metadata["code"] == "white_label_enabled"
    assert evento.event_metadata["anterior"] is None
    assert evento.event_metadata["nuevo"] is True
    assert evento.event_metadata["gac_user"] == GAC_USER


def test_reemplazar_guarda_el_valor_anterior(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Marca", tipo="RESELLER")
    url = f"/api/v1/internal/accounts/{cuenta.id}/capabilities/max_sub_accounts"
    client.put(url, json={"value": 10}, headers=_gac())
    r = client.put(url, json={"value": 25}, headers=_gac())

    assert r.json()["own_value"] == 25
    filas = (
        db_session.query(AccountCapability)
        .filter(AccountCapability.account_id == cuenta.id)
        .all()
    )
    assert len(filas) == 1  # reemplaza, no duplica
    ultimo = [
        e for e in _eventos(db_session, cuenta) if e.event_metadata.get("nuevo") == 25
    ][0]
    assert ultimo.event_metadata["anterior"] == 10


def test_el_techo_del_ancestro_recorta_y_se_dice_quien(client, db_session, catalogo):
    """GAC tiene que ver que el valor que escribió no es el que rige."""
    marca = _cuenta(db_session, "Marca", tipo="RESELLER")
    hija = _cuenta(db_session, "Cliente", padre=marca)
    client.put(
        f"/api/v1/internal/accounts/{marca.id}/capabilities/white_label_enabled",
        json={"value": False},
        headers=_gac(),
    )

    r = client.put(
        f"/api/v1/internal/accounts/{hija.id}/capabilities/white_label_enabled",
        json={"value": True},
        headers=_gac(),
    )

    cuerpo = r.json()
    assert cuerpo["own_value"] is True
    assert cuerpo["effective_value"] is False
    assert cuerpo["source"] == "ancestro"
    assert cuerpo["limited_by"] == str(marca.id)
    assert not account_capabilities.puede(db_session, hija.id, "white_label_enabled")


@pytest.mark.parametrize(
    "code,valor",
    [
        ("white_label_enabled", 1),  # un entero no es un booleano
        ("white_label_enabled", "true"),
        ("max_sub_accounts", True),  # un booleano no es un entero
        ("max_sub_accounts", "5"),
        ("max_sub_accounts", -1),
    ],
)
def test_el_tipo_del_valor_se_valida_sin_convertir(
    client, db_session, catalogo, code, valor
):
    cuenta = _cuenta(db_session, "Marca", tipo="RESELLER")
    r = client.put(
        f"/api/v1/internal/accounts/{cuenta.id}/capabilities/{code}",
        json={"value": valor},
        headers=_gac(),
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert _fila(db_session, cuenta, catalogo[code]) is None
    assert _eventos(db_session, cuenta) == []


@pytest.mark.parametrize("code", ["max_devices", "no_existe"])
def test_solo_se_escriben_capabilities_comerciales(client, db_session, catalogo, code):
    cuenta = _cuenta(db_session, "Marca", tipo="RESELLER")
    r = client.put(
        f"/api/v1/internal/accounts/{cuenta.id}/capabilities/{code}",
        json={"value": 5},
        headers=_gac(),
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND
    assert (
        db_session.query(AccountCapability)
        .filter(AccountCapability.account_id == cuenta.id)
        .count()
        == 0
    )


def test_una_fila_caducada_no_cuenta(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Marca", tipo="RESELLER")
    ayer = (utcnow() - timedelta(days=1)).isoformat() + "Z"
    r = client.put(
        f"/api/v1/internal/accounts/{cuenta.id}/capabilities/white_label_enabled",
        json={"value": True, "expires_at": ayer},
        headers=_gac(),
    )
    cuerpo = r.json()
    assert cuerpo["own_value"] is True
    assert cuerpo["expired"] is True
    assert cuerpo["effective_value"] is False
    assert cuerpo["source"] == "default"


def test_quitar_vuelve_a_heredar_y_es_idempotente(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Marca", tipo="RESELLER")
    url = f"/api/v1/internal/accounts/{cuenta.id}/capabilities/white_label_enabled"
    client.put(url, json={"value": True}, headers=_gac())

    r = client.delete(url, headers=_gac())
    assert r.status_code == status.HTTP_204_NO_CONTENT
    assert _fila(db_session, cuenta, catalogo["white_label_enabled"]) is None
    assert not account_capabilities.puede(db_session, cuenta.id, "white_label_enabled")

    quitado = [
        e
        for e in _eventos(db_session, cuenta)
        if e.event_type == "account_capability_removed"
    ]
    assert len(quitado) == 1
    assert quitado[0].event_metadata["anterior"] is True

    # Otra vez: 204 y sin evento nuevo.
    r = client.delete(url, headers=_gac())
    assert r.status_code == status.HTTP_204_NO_CONTENT
    assert (
        len(
            [
                e
                for e in _eventos(db_session, cuenta)
                if e.event_type == "account_capability_removed"
            ]
        )
        == 1
    )


def test_camino_roto_es_409_y_no_inventa_valor(client, db_session, catalogo):
    cuenta = _cuenta(db_session, "Rota")
    cuenta.account_path = []
    db_session.commit()
    r = client.get(
        f"/api/v1/internal/accounts/{cuenta.id}/capabilities", headers=_gac()
    )
    assert r.status_code == status.HTTP_409_CONFLICT

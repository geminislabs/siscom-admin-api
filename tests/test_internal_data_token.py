"""`POST /api/v1/internal/data-token`: el data token del mapa de dispositivos de GAC."""

import json

import pytest
from fastapi import status

from app.api.deps import (
    AuthResult,
    get_auth_for_gac_admin,
    get_data_token_issuer,
    get_scope_store,
)
from app.main import app
from app.services.data_token_issuance import gac_owner_id, revoke_sessions_for_user
from app.services.scope_store import ScopePurpose, ScopeStore, owner_key, scope_keys
from tests.test_data_token_issuance import (  # noqa: F401 (fixtures)
    _payload,
    fake_valkey,
    fleet,
    issuer,
    keypair,
    store,
)

URL = "/api/v1/internal/data-token"
GAC_USER = "5b1f8c12-3456-4789-a012-3456789abcde"


@pytest.fixture
def gac(client, issuer, store):  # noqa: F811
    app.dependency_overrides[get_auth_for_gac_admin] = lambda: AuthResult(
        auth_type="paseto",
        payload={"service": "gac", "role": "GAC_ADMIN", "internal_id": GAC_USER},
        service="gac",
        role="GAC_ADMIN",
    )
    app.dependency_overrides[get_data_token_issuer] = lambda: issuer
    app.dependency_overrides[get_scope_store] = lambda: store
    yield client


def _scope_ref(keypair, token):  # noqa: F811
    return _payload(keypair[1], token)["scope_ref"]


def test_emite_un_token_con_el_ref_de_cada_imei(gac, fleet, keypair):  # noqa: F811
    dispositivo = fleet["devices"][1]

    respuesta = gac.post(URL, json={"device_ids": [dispositivo.device_id]})

    assert respuesta.status_code == status.HTTP_200_OK, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["token_type"] == "Bearer"
    assert cuerpo["expires_in"] == 600
    assert cuerpo["devices"] == [
        {"device_id": dispositivo.device_id, "device_ref": str(dispositivo.device_ref)}
    ]
    assert _payload(keypair[1], cuerpo["token"])["aud"] == "siscom-api"


def test_el_alcance_es_solo_lo_pedido_y_con_todo_el_historico(
    gac, fleet, keypair, fake_valkey  # noqa: F811
):
    pedido, otro = fleet["devices"]

    cuerpo = gac.post(URL, json={"device_ids": [pedido.device_id]}).json()

    dev_key, unit_key = scope_keys(_scope_ref(keypair, cuerpo["token"]))
    assert set(fake_valkey.hashes[dev_key]) == {str(pedido.device_ref)}
    assert fake_valkey.hget(dev_key, str(otro.device_ref)) is None
    concesion = json.loads(fake_valkey.hget(dev_key, str(pedido.device_ref)))
    assert concesion["id"] == pedido.device_id
    # Histórico y en vivo: lo que el mapa de GAC ya muestra.
    assert concesion["windows"] == [{"from": None, "to": None}]
    # Sin unidades: GAC lee dispositivos, no flotas.
    assert unit_key not in fake_valkey.hashes


def test_repetidos_y_espacios_se_limpian(gac, fleet):  # noqa: F811
    imei = fleet["devices"][0].device_id

    cuerpo = gac.post(URL, json={"device_ids": [imei, f" {imei} "]}).json()

    assert [d["device_id"] for d in cuerpo["devices"]] == [imei]


def test_un_imei_que_no_existe_da_404_y_no_emite(gac, fleet, fake_valkey):  # noqa: F811
    imei = fleet["devices"][0].device_id

    respuesta = gac.post(URL, json={"device_ids": [imei, "000000000000000"]})

    assert respuesta.status_code == status.HTTP_404_NOT_FOUND
    assert respuesta.json()["missing"] == ["000000000000000"]
    assert fake_valkey.hashes == {}


@pytest.mark.parametrize(
    "device_ids",
    [[], [" "], [str(i).zfill(15) for i in range(51)]],
    ids=["vacio", "en-blanco", "mas-de-50"],
)
def test_peticiones_invalidas_son_422(gac, device_ids):
    respuesta = gac.post(URL, json={"device_ids": device_ids})
    assert respuesta.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_queda_en_el_indice_del_operador_de_gac(
    gac, fleet, keypair, fake_valkey  # noqa: F811
):
    cuerpo = gac.post(URL, json={"device_ids": [fleet["devices"][0].device_id]}).json()

    indice = owner_key(gac_owner_id(GAC_USER), ScopePurpose.GAC)
    assert fake_valkey.smembers(indice) == {
        _scope_ref(keypair, cuerpo["token"]).encode()
    }


def test_revocar_sesiones_de_nexus_no_toca_los_tokens_de_gac(
    gac, fleet, keypair, fake_valkey, store, test_user_data  # noqa: F811
):
    cuerpo = gac.post(URL, json={"device_ids": [fleet["devices"][0].device_id]}).json()
    dev_key, _ = scope_keys(_scope_ref(keypair, cuerpo["token"]))

    revoke_sessions_for_user(store, test_user_data.id)

    assert dev_key in fake_valkey.hashes


def test_503_sin_valkey(gac, fleet):  # noqa: F811
    app.dependency_overrides[get_scope_store] = lambda: ScopeStore(None)

    respuesta = gac.post(URL, json={"device_ids": [fleet["devices"][0].device_id]})

    assert respuesta.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


# --- autenticación real -----------------------------------------------------


def test_sin_token_es_401(client):
    respuesta = client.post(URL, json={"device_ids": ["1"]})
    assert respuesta.status_code == status.HTTP_401_UNAUTHORIZED


def test_con_el_paseto_de_gac_de_verdad(client, fleet, issuer, store):  # noqa: F811
    """Sin override de la autenticación: pasa por `decode_service_token`."""
    from app.utils.paseto_token import generate_service_token

    app.dependency_overrides[get_data_token_issuer] = lambda: issuer
    app.dependency_overrides[get_scope_store] = lambda: store
    token, _ = generate_service_token(
        "gac", "GAC_ADMIN", additional_claims={"internal_id": GAC_USER}
    )

    respuesta = client.post(
        URL,
        json={"device_ids": [fleet["devices"][0].device_id]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert respuesta.status_code == status.HTTP_200_OK, respuesta.text


def test_otro_rol_de_servicio_es_403(client):
    from app.utils.paseto_token import generate_service_token

    token, _ = generate_service_token("gac", "NEXUS_LECTOR")
    respuesta = client.post(
        URL, json={"device_ids": ["1"]}, headers={"Authorization": f"Bearer {token}"}
    )
    assert respuesta.status_code == status.HTTP_403_FORBIDDEN

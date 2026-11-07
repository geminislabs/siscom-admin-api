"""Política de versiones de las apps móviles (D2) y `GET /api/v1/client-config`."""

import pytest
from fastapi import status

from app.models.client_version_policy import ClientVersionPolicy
from app.services.client_version_policy import Actualizacion, evaluar, parse_version

# ---------------------------------------------------------------------------
# Comparación
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valor, esperado",
    [
        ("1.2.0", (1, 2, 0)),
        ("1.10", (1, 10)),
        (" v2.0.1 ", (2, 0, 1)),
        ("1.2.0-beta.1", (1, 2, 0)),
        ("1.2.0+45", (1, 2, 0)),
        ("", None),
        (None, None),
        ("abc", None),
        ("1..2", None),
        ("1.2.x", None),
        ("１.２", None),  # dígitos no ASCII
        ("1." + "1" * 200, None),  # demasiado larga
    ],
)
def test_parse_version(valor, esperado):
    assert parse_version(valor) == esperado


def _evaluar(version, minimo=None, ultima=None, bloqueadas=()):
    return evaluar(
        version,
        min_supported_version=minimo,
        latest_version=ultima,
        blocked_versions=bloqueadas,
    )


def test_la_comparacion_es_numerica_y_no_de_cadenas():
    """Como cadenas, "1.10.0" < "1.9.0"."""
    assert _evaluar("1.10.0", minimo="1.9.0") is Actualizacion.NONE
    assert _evaluar("1.9.0", minimo="1.10.0") is Actualizacion.REQUIRED


def test_sin_politica_no_pasa_nada():
    assert _evaluar("0.0.1") is Actualizacion.NONE


def test_por_debajo_del_minimo_es_obligatoria():
    assert _evaluar("1.1.9", minimo="1.2.0", ultima="1.3.0") is Actualizacion.REQUIRED


def test_el_minimo_exacto_vale():
    assert _evaluar("1.2", minimo="1.2.0") is Actualizacion.NONE


def test_entre_minimo_y_ultima_es_opcional():
    assert _evaluar("1.2.5", minimo="1.2.0", ultima="1.3.0") is Actualizacion.OPTIONAL


def test_la_ultima_no_pide_nada():
    assert _evaluar("1.3.0", minimo="1.2.0", ultima="1.3.0") is Actualizacion.NONE


def test_una_version_bloqueada_es_obligatoria_aunque_supere_el_minimo():
    assert (
        _evaluar("1.3.0", minimo="1.2.0", ultima="1.4.0", bloqueadas=["1.3.0"])
        is Actualizacion.REQUIRED
    )


def test_una_version_ilegible_no_bloquea():
    assert _evaluar("rota", minimo="9.0.0") is Actualizacion.NONE
    assert _evaluar(None, minimo="9.0.0") is Actualizacion.NONE


def test_un_umbral_mal_escrito_en_la_tabla_no_bloquea_a_todos():
    assert _evaluar("1.0.0", minimo="uno punto dos") is Actualizacion.NONE


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def politica_ios(db_session):
    """La fila sembrada por la 047, con valores de prueba."""
    fila = db_session.get(ClientVersionPolicy, "ios")
    fila.min_supported_version = "1.2.0"
    fila.latest_version = "1.3.0"
    fila.blocked_versions = ["1.2.1"]
    fila.store_url = "https://apps.apple.com/app/id000"
    db_session.commit()
    return fila


def _consultar(client, **params):
    return client.get("/api/v1/client-config", params=params)


def test_la_semilla_no_cambia_nada_al_desplegar(client):
    for plataforma in ("ios", "android"):
        respuesta = _consultar(client, platform=plataforma, version="0.0.1")
        assert respuesta.status_code == status.HTTP_200_OK
        assert respuesta.json() == {
            "update": "none",
            "latest_version": None,
            "min_supported_version": None,
            "store_url": None,
        }


@pytest.mark.parametrize(
    "version, esperado",
    [
        ("1.1.0", "required"),
        ("1.2.1", "required"),
        ("1.2.5", "optional"),
        ("1.3.0", "none"),
    ],
)
def test_responde_segun_la_politica(client, politica_ios, version, esperado):
    respuesta = _consultar(client, platform="ios", version=version, build="45")

    assert respuesta.status_code == status.HTTP_200_OK
    cuerpo = respuesta.json()
    assert cuerpo["update"] == esperado
    assert cuerpo["min_supported_version"] == "1.2.0"
    assert cuerpo["latest_version"] == "1.3.0"
    assert cuerpo["store_url"] == "https://apps.apple.com/app/id000"


def test_la_plataforma_no_distingue_mayusculas(client, politica_ios):
    assert _consultar(client, platform="iOS", version="1.1.0").json()["update"] == (
        "required"
    )


@pytest.mark.parametrize("params", [{}, {"platform": "windows"}, {"platform": ""}])
def test_sin_plataforma_valida_da_400(client, params):
    assert (
        _consultar(client, version="1.0.0", **params).status_code
        == status.HTTP_400_BAD_REQUEST
    )


def test_no_pide_autenticacion(client):
    """Una app que ya no sabe autenticarse es la que más necesita la respuesta."""
    respuesta = _consultar(client, platform="android", version="1.0.0")
    assert respuesta.status_code == status.HTTP_200_OK

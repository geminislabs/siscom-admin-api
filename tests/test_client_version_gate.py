"""El middleware que responde 426 a las versiones obligadas a actualizar (D2)."""

import json
import logging

import pytest

from app.api import client_version_gate as gate
from app.observability.client_info import client_info_ctx, normalizar
from app.observability.logging import JSONFormatter

POLITICA = {
    "ios": {
        "min_supported_version": "1.2.0",
        "latest_version": "1.3.0",
        "blocked_versions": [],
        "store_url": "https://apps.apple.com/app/id000",
    }
}

# Cualquier ruta protegida: el middleware decide antes que la autenticación.
RUTA = "/api/v1/units"


@pytest.fixture
def politica():
    llamadas = []

    def cargar():
        llamadas.append(1)
        return POLITICA

    gate.usar_cargador(cargar)
    yield llamadas
    gate.usar_cargador(lambda: {})


def _cabeceras(version, plataforma="ios", **extra):
    return {"X-Client-Platform": plataforma, "X-Client-Version": version, **extra}


def test_una_version_por_debajo_del_minimo_recibe_426(client, politica):
    respuesta = client.get(RUTA, headers=_cabeceras("1.1.0"))

    assert respuesta.status_code == 426
    cuerpo = respuesta.json()
    assert cuerpo["error_code"] == "upgrade_required"
    assert cuerpo["store_url"] == "https://apps.apple.com/app/id000"
    assert "Actualiza la app" in cuerpo["detail"]


def test_el_mensaje_sigue_el_idioma(client, politica):
    respuesta = client.get(
        RUTA, headers=_cabeceras("1.1.0", **{"Accept-Language": "en-US,en;q=0.9"})
    )
    assert "Update the app" in respuesta.json()["detail"]


@pytest.mark.parametrize(
    "cabeceras",
    [
        {},  # la web
        {"X-Client-Platform": "ios"},  # media cabecera
        {"X-Client-Version": "1.1.0"},
        _cabeceras("1.2.5"),  # aviso opcional: no bloquea
        _cabeceras("1.1.0", plataforma="android"),  # sin política para android
        _cabeceras("no-es-una-version!"),  # ilegible
    ],
)
def test_lo_demas_pasa(client, politica, cabeceras):
    assert client.get(RUTA, headers=cabeceras).status_code != 426


@pytest.mark.parametrize(
    "ruta", ["/api/v1/client-config?platform=ios", "/api/v1/auth/logout"]
)
def test_las_rutas_exentas_pasan_aunque_haya_que_actualizar(client, politica, ruta):
    """La app obligada a actualizar tiene que poder preguntar qué hacer y salir."""
    metodo = client.post if ruta.endswith("logout") else client.get
    assert metodo(ruta, headers=_cabeceras("1.1.0")).status_code != 426


def test_la_politica_se_cachea(client, politica):
    for _ in range(3):
        client.get(RUTA, headers=_cabeceras("1.1.0"))
    assert len(politica) == 1


def test_si_la_politica_no_se_puede_leer_deja_pasar(client, caplog):
    def roto():
        raise RuntimeError("Postgres no responde")

    gate.usar_cargador(roto)
    try:
        respuesta = client.get(RUTA, headers=_cabeceras("1.1.0"))
    finally:
        gate.usar_cargador(lambda: {})

    assert respuesta.status_code != 426


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


def _formatear():
    registro = logging.LogRecord("x", logging.INFO, __file__, 1, "hola", None, None)
    return json.loads(JSONFormatter().format(registro))


def test_los_logs_llevan_la_plataforma_y_la_version():
    token = client_info_ctx.set(normalizar("iOS", "1.2.0"))
    try:
        linea = _formatear()
    finally:
        client_info_ctx.reset(token)
    assert linea["client_platform"] == "ios"
    assert linea["client_version"] == "1.2.0"


def test_sin_cabeceras_los_logs_no_cambian():
    linea = _formatear()
    assert "client_platform" not in linea
    assert "client_version" not in linea


@pytest.mark.parametrize(
    "plataforma, version",
    [("windows", "1.0"), ("ios", "1.0\ninyectado"), ("ios", "x" * 40)],
)
def test_lo_que_no_encaja_se_descarta_entero(plataforma, version):
    info = normalizar(plataforma, version)
    assert info.platform in (None, "ios")
    if plataforma == "windows":
        assert info.platform is None
    else:
        assert info.version is None

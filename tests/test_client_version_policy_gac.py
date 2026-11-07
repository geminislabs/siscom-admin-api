"""`/api/v1/client-version-policy`: la política de versiones administrada desde GAC."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import status

from app.api.deps import AuthResult, get_auth_for_gac_admin
from app.main import app
from app.models.client_version_policy import ClientVersionPolicy
from app.models.mobility_device import MobilityDevice
from app.services.client_version_policy import PoliticaInvalida, validar_politica

BASE = "/api/v1/client-version-policy"
IOS_URL = "https://apps.apple.com/mx/app/nexus-geminislabs/id6760983231"
ANDROID_URL = "https://play.google.com/store/apps/details?id=com.geminislabs.nexus"
GAC_USER = "5b1f8c12-3456-4789-a012-3456789abcde"


@pytest.fixture
def gac(client):
    app.dependency_overrides[get_auth_for_gac_admin] = lambda: AuthResult(
        auth_type="paseto",
        payload={"service": "gac", "role": "GAC_ADMIN", "internal_id": GAC_USER},
        service="gac",
        role="GAC_ADMIN",
    )
    yield client
    app.dependency_overrides.pop(get_auth_for_gac_admin, None)


def _cuerpo(**cambios):
    cuerpo = {
        "min_supported_version": None,
        "latest_version": None,
        "blocked_versions": [],
        "store_url": IOS_URL,
    }
    cuerpo.update(cambios)
    return cuerpo


@pytest.fixture
def instalaciones(db_session, test_user_data):
    """iOS: 3 en 1.1.0, 2 en 1.0.1, 1 sin versión y 1 vieja (fuera de 30 días)."""
    ahora = datetime.now(timezone.utc)

    def equipo(version, plataforma="ios", visto=ahora):
        return MobilityDevice(
            user_id=test_user_data.id,
            device_type="PHONE",
            platform=plataforma,
            app_version=version,
            last_seen_at=visto,
        )

    db_session.add_all(
        [equipo("1.1.0") for _ in range(3)]
        + [equipo("1.0.1"), equipo("1.0.1"), equipo(None), equipo("")]
        + [equipo("0.9.0", visto=ahora - timedelta(days=45))]
        + [equipo("1.1.0", plataforma="android")]
    )
    db_session.commit()


# --- validar_politica -------------------------------------------------------


@pytest.mark.parametrize(
    "cambios, campo",
    [
        ({"min_supported_version": "uno"}, "min_supported_version"),
        ({"latest_version": "1.x"}, "latest_version"),
        (
            {"min_supported_version": "1.3", "latest_version": "1.2.9"},
            "min_supported_version",
        ),
        ({"blocked_versions": ["1.2.0", "1.2"]}, "blocked_versions"),
        ({"blocked_versions": ["nope"]}, "blocked_versions"),
        ({"blocked_versions": [f"1.0.{i}" for i in range(51)]}, "blocked_versions"),
        ({"store_url": "http://apps.apple.com/app/id1"}, "store_url"),
        ({"store_url": ANDROID_URL}, "store_url"),
        ({"store_url": "https://apps.apple.com.evil.com/app"}, "store_url"),
        ({"min_supported_version": "1.2.0", "store_url": None}, "store_url"),
        ({"blocked_versions": ["1.2.1"], "store_url": "  "}, "store_url"),
    ],
)
def test_validar_rechaza_y_dice_el_campo(cambios, campo):
    with pytest.raises(PoliticaInvalida) as exc:
        validar_politica("ios", **_cuerpo(**cambios))
    assert exc.value.campo == campo


def test_validar_limpia_y_acepta():
    fila = validar_politica(
        "ios",
        min_supported_version=" 1.2.0 ",
        latest_version="v1.10",
        blocked_versions=[" 1.2.1"],
        store_url=f" {IOS_URL} ",
    )
    assert fila == {
        "min_supported_version": "1.2.0",
        "latest_version": "v1.10",
        "blocked_versions": ["1.2.1"],
        "store_url": IOS_URL,
    }


def test_validar_vacios_son_null():
    fila = validar_politica(
        "android",
        min_supported_version="",
        latest_version="  ",
        blocked_versions=[],
        store_url="",
    )
    assert fila == {
        "min_supported_version": None,
        "latest_version": None,
        "blocked_versions": [],
        "store_url": None,
    }


# --- GET y PUT --------------------------------------------------------------


def test_get_devuelve_las_dos_filas_sembradas(gac):
    respuesta = gac.get(BASE)
    assert respuesta.status_code == status.HTTP_200_OK
    filas = respuesta.json()
    assert [f["platform"] for f in filas] == ["android", "ios"]
    assert set(filas[0]) == {
        "platform",
        "min_supported_version",
        "latest_version",
        "blocked_versions",
        "store_url",
        "updated_at",
        "updated_by",
    }


def test_put_guarda_la_fila_entera_y_la_firma(gac, db_session):
    respuesta = gac.put(
        f"{BASE}/ios",
        json=_cuerpo(
            min_supported_version="1.2.0",
            latest_version="1.3.0",
            blocked_versions=["1.2.1"],
        ),
    )
    assert respuesta.status_code == status.HTTP_200_OK, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["platform"] == "ios"
    assert cuerpo["min_supported_version"] == "1.2.0"
    assert cuerpo["blocked_versions"] == ["1.2.1"]
    assert cuerpo["updated_by"] == f"gac:{GAC_USER}"
    assert cuerpo["updated_at"]

    db_session.expire_all()
    fila = db_session.get(ClientVersionPolicy, "ios")
    assert fila.store_url == IOS_URL
    assert fila.updated_by == f"gac:{GAC_USER}"


def test_put_llega_a_client_config_al_instante(gac):
    gac.put(f"{BASE}/ios", json=_cuerpo(min_supported_version="1.2.0"))
    config = gac.get(
        "/api/v1/client-config", params={"platform": "ios", "version": "1.1.0"}
    ).json()
    assert config["update"] == "required"
    assert config["store_url"] == IOS_URL


def test_put_vacia_la_cache_del_middleware(gac, db_session):
    """Sin `invalidar_cache` el worker que guardó seguiría 60 s con la política vieja."""
    from app.api import client_version_gate as gate

    def de_la_base():
        return {
            fila.platform: {
                "min_supported_version": fila.min_supported_version,
                "latest_version": fila.latest_version,
                "blocked_versions": list(fila.blocked_versions or ()),
                "store_url": fila.store_url,
            }
            for fila in db_session.query(ClientVersionPolicy).all()
        }

    gate.usar_cargador(de_la_base)
    vieja = {"X-Client-Platform": "ios", "X-Client-Version": "1.1.0"}
    # Llena la caché con la política sembrada (sin mínimo): la 1.1.0 pasa.
    assert gac.get("/api/v1/units", headers=vieja).status_code != 426

    gac.put(f"{BASE}/ios", json=_cuerpo(min_supported_version="1.2.0"))

    assert gac.get("/api/v1/units", headers=vieja).status_code == 426


def test_put_422_trae_detail_y_field(gac):
    respuesta = gac.put(f"{BASE}/ios", json=_cuerpo(store_url=ANDROID_URL))
    assert respuesta.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert respuesta.json() == {
        "detail": "store_url debe ser https://apps.apple.com/…",
        "field": "store_url",
    }


@pytest.mark.parametrize(
    "cuerpo, campo",
    [
        ({k: v for k, v in _cuerpo().items() if k != "store_url"}, "store_url"),
        (_cuerpo(blocked_versions="1.2.0"), "blocked_versions"),
        (_cuerpo(extra="x"), "extra"),
    ],
)
def test_los_422_de_fastapi_tambien_traen_field(gac, cuerpo, campo):
    respuesta = gac.put(f"{BASE}/ios", json=cuerpo)
    assert respuesta.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert respuesta.json()["field"] == campo
    assert isinstance(respuesta.json()["detail"], str)


def test_put_sin_cambiar_nada_si_es_invalido(gac, db_session):
    gac.put(
        f"{BASE}/ios", json=_cuerpo(min_supported_version="1.3", latest_version="1.2")
    )
    db_session.expire_all()
    assert db_session.get(ClientVersionPolicy, "ios").min_supported_version is None


def test_plataforma_desconocida_es_404(gac):
    assert gac.put(f"{BASE}/windows", json=_cuerpo()).status_code == 404
    assert gac.get(f"{BASE}/windows/installs").status_code == 404
    assert gac.post(f"{BASE}/windows/preview", json=_cuerpo()).status_code == 404


# --- installs y preview -----------------------------------------------------


def test_installs_cuenta_por_version_en_la_ventana(gac, instalaciones):
    respuesta = gac.get(f"{BASE}/ios/installs", params={"days": 30})
    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.json() == {
        "platform": "ios",
        "days": 30,
        "total": 7,
        "versions": [
            {"app_version": "1.1.0", "installs": 3},
            {"app_version": "1.0.1", "installs": 2},
            {"app_version": "desconocida", "installs": 2},
        ],
    }


def test_installs_amplia_la_ventana(gac, instalaciones):
    cuerpo = gac.get(f"{BASE}/ios/installs", params={"days": 60}).json()
    assert cuerpo["total"] == 8


@pytest.mark.parametrize("dias", [0, 366])
def test_installs_dias_fuera_de_rango(gac, dias):
    respuesta = gac.get(f"{BASE}/ios/installs", params={"days": dias})
    assert respuesta.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert respuesta.json()["field"] == "days"


def test_preview_clasifica_y_no_guarda(gac, instalaciones, db_session):
    respuesta = gac.post(
        f"{BASE}/ios/preview",
        json=_cuerpo(min_supported_version="1.1.0", latest_version="1.2.0"),
    )
    assert respuesta.status_code == status.HTTP_200_OK, respuesta.text
    assert respuesta.json() == {
        "platform": "ios",
        "days": 30,
        "total": 7,
        "required": 2,
        "optional": 3,
        "versions": [
            {"app_version": "1.1.0", "installs": 3, "update": "optional"},
            {"app_version": "1.0.1", "installs": 2, "update": "required"},
            {"app_version": "desconocida", "installs": 2, "update": "none"},
        ],
    }
    db_session.expire_all()
    assert db_session.get(ClientVersionPolicy, "ios").min_supported_version is None


def test_preview_bloqueada_es_required(gac, instalaciones):
    cuerpo = gac.post(
        f"{BASE}/ios/preview", json=_cuerpo(blocked_versions=["1.1"])
    ).json()
    assert cuerpo["required"] == 3
    assert cuerpo["optional"] == 0


def test_preview_devuelve_los_mismos_422(gac):
    respuesta = gac.post(f"{BASE}/ios/preview", json=_cuerpo(latest_version="x"))
    assert respuesta.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert respuesta.json()["field"] == "latest_version"


# --- autenticación real -----------------------------------------------------


def test_sin_token_es_401(client):
    assert client.get(BASE).status_code == status.HTTP_401_UNAUTHORIZED


def test_con_el_paseto_de_gac_de_verdad(client):
    """Sin override: pasa por `decode_service_token`, como en producción."""
    from app.utils.paseto_token import generate_service_token

    token, _ = generate_service_token(
        "gac", "GAC_ADMIN", additional_claims={"internal_id": GAC_USER}
    )
    respuesta = client.put(
        f"{BASE}/android",
        json=_cuerpo(latest_version="1.2.0", store_url=ANDROID_URL),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert respuesta.status_code == status.HTTP_200_OK, respuesta.text
    assert respuesta.json()["updated_by"] == f"gac:{GAC_USER}"


def test_otro_rol_de_servicio_es_403(client):
    from app.utils.paseto_token import generate_service_token

    token, _ = generate_service_token("gac", "NEXUS_LECTOR")
    respuesta = client.get(BASE, headers={"Authorization": f"Bearer {token}"})
    assert respuesta.status_code == status.HTTP_403_FORBIDDEN

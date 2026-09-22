"""
Tests de integración para PasetoTokenGenerator y helpers de app.utils.paseto_token.

Usa claves conocidas (base64), pyseto real y mocks mínimos solo para tiempo/expiración
y ramas imposibles de alcanzar con tokens bien formados.
"""

import base64
import importlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest


def _b64_key(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


@pytest.fixture
def secret_32_bytes() -> bytes:
    return bytes(range(32))


@pytest.fixture
def paseto_secret_b64(secret_32_bytes) -> str:
    """Clave de los tokens de SERVICIO (`internal-*`)."""
    return _b64_key(secret_32_bytes)


@pytest.fixture
def share_secret_b64() -> str:
    """Clave de los tokens de compartir ubicación. Distinta de la de servicio."""
    return _b64_key(bytes(range(100, 132)))


@pytest.fixture
def _patched_keys(monkeypatch, paseto_secret_b64, share_secret_b64):
    """Parchea ambas claves para no depender del .env."""
    assert paseto_secret_b64 != share_secret_b64
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY",
        paseto_secret_b64,
    )
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.SHARE_LOCATION_KEY_B64",
        share_secret_b64,
    )


@pytest.fixture
def paseto_generator(_patched_keys):
    """PasetoTokenGenerator con claves controladas (sin depender del .env)."""
    from app.utils.paseto_token import PasetoTokenGenerator

    return PasetoTokenGenerator()


@pytest.fixture
def paseto_module_reloaded(_patched_keys):
    """Módulo recargado para que el singleton use las claves parcheadas."""
    import app.utils.paseto_token as pt

    return importlib.reload(pt)


def test_generator_raises_when_pyseto_rejects_key(_patched_keys):
    """Si la clave resultante es inválida para v4.local, falla en Key.new."""
    from app.utils.paseto_token import PasetoTokenGenerator

    with patch("app.utils.paseto_token.Key") as mock_key:
        mock_key.new.side_effect = ValueError("bad key material")
        with pytest.raises(ValueError, match="bad key material"):
            PasetoTokenGenerator()


def test_service_key_pads_secret_shorter_than_32_bytes(monkeypatch, share_secret_b64):
    """El relleno histórico se conserva SOLO en la clave de servicio."""
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY",
        _b64_key(b"only-10-ch"),
    )
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.SHARE_LOCATION_KEY_B64", share_secret_b64
    )
    from app.utils.paseto_token import PasetoTokenGenerator

    gen = PasetoTokenGenerator()
    token, _exp = gen.generate_service_token("gac", "GAC_ADMIN")
    out = gen.decode_service_token(token)
    assert out is not None
    assert out["service"] == "gac"


def test_service_key_truncates_secret_longer_than_32_bytes(
    monkeypatch, share_secret_b64
):
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY",
        _b64_key(b"a" * 40),
    )
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.SHARE_LOCATION_KEY_B64", share_secret_b64
    )
    from app.utils.paseto_token import PasetoTokenGenerator

    gen = PasetoTokenGenerator()
    token, _exp = gen.generate_service_token("gac", "GAC_ADMIN")
    assert gen.decode_service_token(token)["role"] == "GAC_ADMIN"


def test_two_generators_same_padded_secret_round_trip(monkeypatch, share_secret_b64):
    """Dos instancias con la misma clave eficaz se decodifican mutuamente."""
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY", _b64_key(b"short")
    )
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.SHARE_LOCATION_KEY_B64", share_secret_b64
    )
    from app.utils.paseto_token import PasetoTokenGenerator

    g1 = PasetoTokenGenerator()
    g2 = PasetoTokenGenerator()
    token, _ = g1.generate_service_token("gac", "GAC_ADMIN")
    assert g2.decode_service_token(token)["service"] == "gac"


def test_generate_share_token_rejects_empty_device_id(paseto_generator):
    with pytest.raises(ValueError, match="no tiene asignado un dispositivo"):
        paseto_generator.generate_share_token(uuid4(), "")


def test_generate_share_token_rejects_none_device_id(paseto_generator):
    with pytest.raises(ValueError, match="no tiene asignado un dispositivo"):
        paseto_generator.generate_share_token(uuid4(), None)  # type: ignore[arg-type]


def test_generate_share_token_payload_shape_and_expiry(paseto_generator):
    unit_id = uuid4()
    device_id = "dev-001"
    token, exp = paseto_generator.generate_share_token(
        unit_id, device_id, expires_in_minutes=45
    )
    assert isinstance(token, str)
    assert token
    payload = paseto_generator.decode_share_token(token)
    assert payload is not None

    assert payload["unit_id"] == str(unit_id)
    assert payload["device_id"] == device_id
    assert payload["scope"] == "public-location-share"
    UUID(payload["share_id"])  # válido como UUID

    iat = datetime.fromisoformat(payload["iat"])
    exp_payload = datetime.fromisoformat(payload["exp"])
    assert exp_payload == exp
    assert exp_payload - iat == timedelta(minutes=45)


def test_decode_share_token_round_trip(paseto_generator):
    uid = uuid4()
    token, exp = paseto_generator.generate_share_token(
        uid, "d-round", expires_in_minutes=5
    )
    data = paseto_generator.decode_share_token(token)
    assert data is not None
    assert datetime.fromisoformat(data["exp"]) == exp


def test_decode_share_token_returns_none_for_wrong_scope(paseto_generator):
    svc_tok, _ = paseto_generator.generate_service_token("gac", "GAC_ADMIN")
    assert paseto_generator.decode_share_token(svc_tok) is None


def test_decode_share_token_returns_none_for_tampered_token(paseto_generator):
    """Un token manipulado no decodifica.

    La version anterior fallaba 1 de cada 63 corridas, y conviene saber por
    que: sustituia el caracter `token[-3]` pero elegia el reemplazo mirando
    `token[-1]`. Cuando el antepenultimo caracter ya era una "X", el
    reemplazo producia otra "X" y `bad` salia **identico al original** — el
    test decodificaba un token intacto y se sorprendia de que funcionara.

    El arreglo es mirar el caracter que se sustituye. Y la linea que de
    verdad cierra el agujero es el `assert bad != token`: sin ella, el test
    puede volver a quedarse sin manipular nada y nadie se entera hasta que
    falla, meses despues, en una corrida que no tiene nada que ver.
    """
    uid = uuid4()
    token, _ = paseto_generator.generate_share_token(uid, "d")
    bad = token[:-3] + ("X" if token[-3] != "X" else "Y") + token[-2:]
    assert bad != token, "el test no manipulo el token: no esta probando nada"
    assert paseto_generator.decode_share_token(bad) is None


def test_decode_share_token_returns_none_when_wrong_key(
    monkeypatch, paseto_generator, paseto_secret_b64, share_secret_b64
):
    uid = uuid4()
    token, _ = paseto_generator.generate_share_token(uid, "d")
    other = _b64_key(bytes(range(32, 64)))
    assert other != share_secret_b64
    monkeypatch.setattr("app.utils.paseto_token.settings.SHARE_LOCATION_KEY_B64", other)
    from app.utils.paseto_token import PasetoTokenGenerator

    other_gen = PasetoTokenGenerator()
    assert other_gen.decode_share_token(token) is None


def test_decode_share_token_returns_none_on_decode_exception(paseto_generator):
    import app.utils.paseto_token as pt

    with patch.object(pt.pyseto, "decode", side_effect=RuntimeError("boom")):
        assert paseto_generator.decode_share_token("v4.anything") is None


def test_decode_share_token_returns_none_on_invalid_json_payload(paseto_generator):
    import app.utils.paseto_token as pt

    decoded = MagicMock()
    decoded.payload = b"not-json{"
    with patch.object(pt.pyseto, "decode", return_value=decoded):
        assert paseto_generator.decode_share_token("v4.local.xxx") is None


def test_decode_share_token_returns_none_without_exp_key(paseto_generator):
    import pyseto

    raw = {
        "share_id": str(uuid4()),
        "unit_id": str(uuid4()),
        "device_id": "d",
        "scope": "public-location-share",
        "iat": datetime.now(timezone.utc).isoformat(),
    }
    token = pyseto.encode(
        key=paseto_generator.share_key,
        payload=json.dumps(raw).encode("utf-8"),
    ).decode("utf-8")
    assert paseto_generator.decode_share_token(token) is None


def test_generate_service_token_payload_and_additional_claims(paseto_generator):
    token, exp = paseto_generator.generate_service_token(
        "gac",
        "GAC_ADMIN",
        expires_in_hours=12,
        additional_claims={"correlation_id": "abc-123"},
    )
    assert isinstance(token, str)
    payload = paseto_generator.decode_service_token(token)
    assert payload is not None
    assert payload["service"] == "gac"
    assert payload["role"] == "GAC_ADMIN"
    assert payload["scope"] == "internal-gac-admin"
    assert payload["correlation_id"] == "abc-123"
    exp_p = datetime.fromisoformat(payload["exp"])
    assert exp_p == exp


def test_generate_service_token_additional_claims_can_override_exp(paseto_generator):
    """Documenta el orden actual: update() permite pisar campos incluido exp."""
    past_exp = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    token, _orig_exp = paseto_generator.generate_service_token(
        "gac",
        "GAC_ADMIN",
        expires_in_hours=24,
        additional_claims={"exp": past_exp},
    )
    assert paseto_generator.decode_service_token(token) is None


def test_decode_service_token_accepts_each_builtin_scope_literal(paseto_generator):
    scopes = [
        "service-auth",
        "internal-nexus-admin",
        "internal-gac-admin",
        "internal-app-admin",
    ]
    for scope in scopes:
        raw_payload = {
            "token_id": str(uuid4()),
            "service": "gac",
            "role": "GAC_ADMIN",
            "scope": scope,
            "iat": datetime.now(timezone.utc).isoformat(),
            "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
        import pyseto

        payload_bytes = json.dumps(raw_payload).encode("utf-8")
        token = pyseto.encode(
            key=paseto_generator.service_key, payload=payload_bytes
        ).decode("utf-8")
        out = paseto_generator.decode_service_token(token)
        assert out is not None, scope
        assert out["scope"] == scope


def test_decode_service_token_flexible_scope_for_gac_internal_prefix(paseto_generator):
    raw_payload = {
        "token_id": str(uuid4()),
        "service": "gac",
        "role": "GAC_ADMIN",
        "scope": "internal-custom-integration",
        "iat": datetime.now(timezone.utc).isoformat(),
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    import pyseto

    payload_bytes = json.dumps(raw_payload).encode("utf-8")
    token = pyseto.encode(
        key=paseto_generator.service_key, payload=payload_bytes
    ).decode("utf-8")
    assert paseto_generator.decode_service_token(token) is not None


def test_decode_service_token_rejects_unknown_scope_without_gac_internal_rule(
    paseto_generator,
):
    raw_payload = {
        "token_id": str(uuid4()),
        "service": "gac",
        "role": "GAC_ADMIN",
        "scope": "public-api",
        "iat": datetime.now(timezone.utc).isoformat(),
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    import pyseto

    token = pyseto.encode(
        key=paseto_generator.service_key,
        payload=json.dumps(raw_payload).encode("utf-8"),
    ).decode("utf-8")
    assert paseto_generator.decode_service_token(token) is None


def test_decode_service_token_rejects_bad_scope_for_non_gac_service(paseto_generator):
    raw_payload = {
        "token_id": str(uuid4()),
        "service": "other",
        "role": "GAC_ADMIN",
        "scope": "internal-weird",
        "iat": datetime.now(timezone.utc).isoformat(),
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    import pyseto

    token = pyseto.encode(
        key=paseto_generator.service_key,
        payload=json.dumps(raw_payload).encode("utf-8"),
    ).decode("utf-8")
    assert paseto_generator.decode_service_token(token) is None


def test_decode_service_token_required_service_mismatch(paseto_generator):
    token, _ = paseto_generator.generate_service_token("gac", "GAC_ADMIN")
    assert (
        paseto_generator.decode_service_token(token, required_service="other") is None
    )


def test_decode_service_token_required_role_mismatch(paseto_generator):
    token, _ = paseto_generator.generate_service_token("gac", "GAC_ADMIN")
    assert paseto_generator.decode_service_token(token, required_role="OTHER") is None


def test_decode_service_token_passes_when_scope_missing_but_exp_valid(paseto_generator):
    """Si scope falta, la validación de lista blanca no rechaza el token."""
    raw_payload = {
        "token_id": str(uuid4()),
        "service": "gac",
        "role": "GAC_ADMIN",
        "iat": datetime.now(timezone.utc).isoformat(),
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    import pyseto

    token = pyseto.encode(
        key=paseto_generator.service_key,
        payload=json.dumps(raw_payload).encode("utf-8"),
    ).decode("utf-8")
    out = paseto_generator.decode_service_token(token)
    assert out is not None
    assert "scope" not in out


def test_decode_service_token_returns_none_without_exp_key(paseto_generator):
    import pyseto

    raw = {"service": "gac", "role": "GAC_ADMIN", "scope": "internal-gac-admin"}
    token = pyseto.encode(
        key=paseto_generator.service_key,
        payload=json.dumps(raw).encode("utf-8"),
    ).decode("utf-8")
    assert paseto_generator.decode_service_token(token) is None


def test_decode_service_token_returns_none_on_decode_error(paseto_generator):
    import app.utils.paseto_token as pt

    with patch.object(pt.pyseto, "decode", side_effect=ValueError("bad")):
        assert paseto_generator.decode_service_token("t") is None


def test_module_helpers_round_trip_after_reload(paseto_module_reloaded):
    pt = paseto_module_reloaded
    uid = uuid4()
    token, _ = pt.generate_location_share_token(uid, "device-helper")
    data = pt.decode_location_share_token(token)
    assert data is not None
    assert data["unit_id"] == str(uid)
    assert data["device_id"] == "device-helper"


def test_generate_service_token_and_decode_helpers(paseto_module_reloaded):
    pt = paseto_module_reloaded
    token, _ = pt.generate_service_token("gac", "GAC_ADMIN", expires_in_hours=1)
    data = pt.decode_service_token(
        token, required_service="gac", required_role="GAC_ADMIN"
    )
    assert data is not None
    assert data["service"] == "gac"


def test_module_singleton_matches_fresh_generator_same_secret(
    monkeypatch, paseto_secret_b64
):
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY",
        paseto_secret_b64,
    )
    import importlib

    import app.utils.paseto_token as pt

    mod = importlib.reload(pt)
    fresh = pt.PasetoTokenGenerator()

    tok1, _ = mod.generate_location_share_token(uuid4(), "d-sg")
    assert fresh.decode_share_token(tok1) is not None

    tok2, _ = fresh.generate_share_token(uuid4(), "d-sg")
    assert mod.decode_location_share_token(tok2) is not None


# ---------------------------------------------------------------------------
# Separación de claves (paso 0 de Fase 1)
#
# Estos tests fijan la propiedad de seguridad, no la implementación: quien
# tenga la clave de compartir ubicación NO debe poder firmar ni verificar
# tokens de servicio internos, y viceversa.
# ---------------------------------------------------------------------------


def test_share_and_service_keys_are_distinct(paseto_generator):
    assert paseto_generator.share_key is not paseto_generator.service_key


def test_share_token_is_not_verifiable_with_the_service_key(paseto_generator):
    """
    El núcleo del paso 0: siscom-api recibe solo la clave de compartir, así que
    un token de compartir no puede validarse ni emitirse con la de servicio.
    """
    import pyseto

    token, _ = paseto_generator.generate_share_token(uuid4(), "dev-x")
    with pytest.raises(pyseto.DecryptError):
        pyseto.decode(keys=paseto_generator.service_key, token=token)


def test_service_token_is_not_verifiable_with_the_share_key(paseto_generator):
    """
    La dirección que cierra la escalada: quien tenga la clave de compartir no
    puede leer —ni por tanto falsificar— tokens `internal-*`.
    """
    import pyseto

    token, _ = paseto_generator.generate_service_token("gac", "GAC_ADMIN")
    with pytest.raises(pyseto.DecryptError):
        pyseto.decode(keys=paseto_generator.share_key, token=token)


def test_token_forged_with_share_key_is_rejected_as_service_token(paseto_generator):
    """
    Simula a siscom-api intentando emitir un token administrativo con la única
    clave que posee. Debe ser rechazado.
    """
    import pyseto

    forged_payload = {
        "token_id": str(uuid4()),
        "service": "gac",
        "role": "GAC_ADMIN",
        "scope": "internal-gac-admin",
        "iat": datetime.now(timezone.utc).isoformat(),
        "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    forged = pyseto.encode(
        key=paseto_generator.share_key,
        payload=json.dumps(forged_payload).encode("utf-8"),
    ).decode("utf-8")

    assert paseto_generator.decode_service_token(forged) is None


def test_missing_share_key_raises_instead_of_falling_back(
    monkeypatch, paseto_secret_b64
):
    """Sin clave de compartir se falla; NUNCA se degrada a la de servicio."""
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY", paseto_secret_b64
    )
    monkeypatch.setattr("app.utils.paseto_token.settings.SHARE_LOCATION_KEY_B64", None)
    from app.utils.paseto_token import (
        PasetoTokenGenerator,
        ShareLocationKeyNotConfigured,
    )

    gen = PasetoTokenGenerator()

    # Los tokens de servicio siguen funcionando: la falta del secreto degrada
    # solo compartir ubicación, no la API entera.
    assert gen.decode_service_token(gen.generate_service_token("gac", "X")[0])

    with pytest.raises(ShareLocationKeyNotConfigured):
        gen.generate_share_token(uuid4(), "dev-x")


@pytest.mark.parametrize(
    "bad_key, reason",
    [
        (_b64_key(b"\x00" * 32), "todo ceros (el valor de .env.example)"),
        (_b64_key(b"too-short"), "menos de 32 bytes"),
        (_b64_key(b"a" * 40), "más de 32 bytes"),
        ("no-es-base64!!", "no es base64"),
    ],
)
def test_invalid_share_key_is_rejected_at_construction(
    monkeypatch, paseto_secret_b64, bad_key, reason
):
    """
    La clave de compartir se valida de forma estricta: nada de rellenar con
    ceros en silencio, que es lo que enmascaraba una clave débil.
    """
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY", paseto_secret_b64
    )
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.SHARE_LOCATION_KEY_B64", bad_key
    )
    from app.utils.paseto_token import PasetoTokenGenerator

    with pytest.raises(ValueError):
        PasetoTokenGenerator()


def test_decode_any_token_no_longer_exists(paseto_generator):
    """
    Aceptaba cualquier token válido sin mirar el scope, así que un token de
    compartir pasaba por uno de servicio. Se elimina en vez de heredarse.
    """
    assert not hasattr(paseto_generator, "decode_any_token")

    import app.utils.paseto_token as pt

    assert not hasattr(pt, "decode_any_token")


def test_padding_warning_names_the_interoperability_consequence(
    monkeypatch, share_secret_b64, caplog
):
    """
    El relleno no solo baja la entropía: hace que un verificador que NO rellena
    derive una clave distinta, así que los tokens no validan aunque los dos lados
    tengan la misma cadena configurada. Ese es el fallo caro, y el aviso tiene
    que nombrarlo — si alguien reescribe el texto y deja solo lo de la entropía,
    este test cae.
    """
    import logging

    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY", _b64_key(b"corta")
    )
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.SHARE_LOCATION_KEY_B64", share_secret_b64
    )
    from app.utils.paseto_token import PasetoTokenGenerator

    with caplog.at_level(logging.WARNING, logger="app.utils.paseto_token"):
        PasetoTokenGenerator()

    message = " ".join(r.getMessage() for r in caplog.records).lower()
    assert "distinta" in message
    assert "no validan" in message


def test_padding_produces_a_different_key_than_no_padding():
    """
    Fija el mecanismo del fallo: con la MISMA cadena de configuración, rellenar y
    no rellenar dan claves efectivas distintas. Es lo que rompe compartir
    ubicación entre servicios que derivan distinto.
    """
    import base64

    from app.utils.paseto_token import _V4_LOCAL_KEY_BYTES

    raw = base64.b64decode(_b64_key(b"veintiun-bytes-justos"))
    assert len(raw) < _V4_LOCAL_KEY_BYTES

    con_relleno = raw.ljust(_V4_LOCAL_KEY_BYTES, b"\0")
    sin_relleno = raw

    assert con_relleno != sin_relleno

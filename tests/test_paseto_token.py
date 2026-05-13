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
    return _b64_key(secret_32_bytes)


@pytest.fixture
def paseto_generator(monkeypatch, paseto_secret_b64):
    """PasetoTokenGenerator con clave controlada (sin depender del .env)."""
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY",
        paseto_secret_b64,
    )
    from app.utils.paseto_token import PasetoTokenGenerator

    return PasetoTokenGenerator()


@pytest.fixture
def paseto_module_reloaded(monkeypatch, paseto_secret_b64):
    """Módulo recargado para que paseto_generator singleton use la clave parcheada."""
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY",
        paseto_secret_b64,
    )
    import app.utils.paseto_token as pt

    return importlib.reload(pt)


def test_generator_raises_when_pyseto_rejects_key(monkeypatch):
    """Si la clave resultante es inválida para v4.local, falla en Key.new."""
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY",
        _b64_key(b"x" * 32),
    )
    from app.utils.paseto_token import PasetoTokenGenerator

    with patch("app.utils.paseto_token.Key") as mock_key:
        mock_key.new.side_effect = ValueError("bad key material")
        with pytest.raises(ValueError, match="bad key material"):
            PasetoTokenGenerator()


def test_generator_pads_secret_shorter_than_32_bytes(monkeypatch):
    raw_short = b"only-10-ch"  # 10 bytes
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY",
        _b64_key(raw_short),
    )
    from app.utils.paseto_token import PasetoTokenGenerator

    gen = PasetoTokenGenerator()
    unit_id = uuid4()
    token, _exp = gen.generate_share_token(unit_id, "device-pad")
    out = gen.decode_share_token(token)
    assert out is not None
    assert out["unit_id"] == str(unit_id)
    assert out["device_id"] == "device-pad"


def test_generator_truncates_secret_longer_than_32_bytes(monkeypatch):
    raw_long = b"a" * 40
    monkeypatch.setattr(
        "app.utils.paseto_token.settings.PASETO_SECRET_KEY",
        _b64_key(raw_long),
    )
    from app.utils.paseto_token import PasetoTokenGenerator

    gen = PasetoTokenGenerator()
    unit_id = uuid4()
    token, _exp = gen.generate_share_token(unit_id, "device-trunc")
    assert gen.decode_share_token(token)["unit_id"] == str(unit_id)


def test_two_generators_same_padded_secret_round_trip(monkeypatch):
    """Dos instancias con la misma clave eficaz pueden decodificar tokens mutuamente."""
    raw = b"short"
    b64 = _b64_key(raw)
    monkeypatch.setattr("app.utils.paseto_token.settings.PASETO_SECRET_KEY", b64)
    from app.utils.paseto_token import PasetoTokenGenerator

    g1 = PasetoTokenGenerator()
    g2 = PasetoTokenGenerator()
    uid = uuid4()
    token, _ = g1.generate_share_token(uid, "d")
    assert g2.decode_share_token(token)["unit_id"] == str(uid)

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
    token, exp = paseto_generator.generate_share_token(uid, "d-round", expires_in_minutes=5)
    data = paseto_generator.decode_share_token(token)
    assert data is not None
    assert datetime.fromisoformat(data["exp"]) == exp


def test_decode_share_token_returns_none_for_wrong_scope(paseto_generator):
    svc_tok, _ = paseto_generator.generate_service_token("gac", "GAC_ADMIN")
    assert paseto_generator.decode_share_token(svc_tok) is None


def test_decode_share_token_returns_none_for_tampered_token(paseto_generator):
    uid = uuid4()
    token, _ = paseto_generator.generate_share_token(uid, "d")
    bad = token[:-3] + ("X" if token[-1] != "X" else "Y") + token[-2:]
    assert paseto_generator.decode_share_token(bad) is None


def test_decode_share_token_returns_none_when_wrong_key(
    monkeypatch, paseto_generator, paseto_secret_b64
):
    uid = uuid4()
    token, _ = paseto_generator.generate_share_token(uid, "d")
    other = _b64_key(bytes(range(32, 64)))
    assert other != paseto_secret_b64
    monkeypatch.setattr("app.utils.paseto_token.settings.PASETO_SECRET_KEY", other)
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
        key=paseto_generator.key,
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
        token = pyseto.encode(key=paseto_generator.key, payload=payload_bytes).decode(
            "utf-8"
        )
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
    token = pyseto.encode(key=paseto_generator.key, payload=payload_bytes).decode("utf-8")
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
        key=paseto_generator.key,
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
        key=paseto_generator.key,
        payload=json.dumps(raw_payload).encode("utf-8"),
    ).decode("utf-8")
    assert paseto_generator.decode_service_token(token) is None


def test_decode_service_token_required_service_mismatch(paseto_generator):
    token, _ = paseto_generator.generate_service_token("gac", "GAC_ADMIN")
    assert paseto_generator.decode_service_token(token, required_service="other") is None


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
        key=paseto_generator.key,
        payload=json.dumps(raw_payload).encode("utf-8"),
    ).decode("utf-8")
    out = paseto_generator.decode_service_token(token)
    assert out is not None
    assert "scope" not in out


def test_decode_service_token_returns_none_without_exp_key(paseto_generator):
    import pyseto

    raw = {"service": "gac", "role": "GAC_ADMIN", "scope": "internal-gac-admin"}
    token = pyseto.encode(
        key=paseto_generator.key,
        payload=json.dumps(raw).encode("utf-8"),
    ).decode("utf-8")
    assert paseto_generator.decode_service_token(token) is None


def test_decode_service_token_returns_none_on_decode_error(paseto_generator):
    import app.utils.paseto_token as pt

    with patch.object(pt.pyseto, "decode", side_effect=ValueError("bad")):
        assert paseto_generator.decode_service_token("t") is None

def test_decode_any_token_accepts_share_and_service_tokens(paseto_generator):
    uid = uuid4()
    share_t, _ = paseto_generator.generate_share_token(uid, "d")
    svc_t, _ = paseto_generator.generate_service_token("gac", "GAC_ADMIN")

    s1 = paseto_generator.decode_any_token(share_t)
    s2 = paseto_generator.decode_any_token(svc_t)
    assert s1 is not None and s1["scope"] == "public-location-share"
    assert s2 is not None and s2["scope"] == "internal-gac-admin"


def test_decode_any_token_returns_none_on_failure(paseto_generator):
    import app.utils.paseto_token as pt

    with patch.object(pt.pyseto, "decode", side_effect=OSError("x")):
        assert paseto_generator.decode_any_token("v4.local.x") is None


def test_decode_any_token_returns_none_on_bad_json(paseto_generator):
    import app.utils.paseto_token as pt

    decoded = MagicMock()
    decoded.payload = b"{{"
    with patch.object(pt.pyseto, "decode", return_value=decoded):
        assert paseto_generator.decode_any_token("t") is None


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
    data = pt.decode_service_token(token, required_service="gac", required_role="GAC_ADMIN")
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

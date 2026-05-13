import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app.utils import recaptcha


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload=None, post_error=None, timeout=10.0):
        self.payload = payload or {}
        self.post_error = post_error
        self.timeout = timeout
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, data):
        self.calls.append({"url": url, "data": data})
        if self.post_error:
            raise self.post_error
        return _FakeResponse(self.payload)


def test_verify_recaptcha_skips_validation_when_secret_is_missing(monkeypatch):
    monkeypatch.setattr(recaptcha.settings, "RECAPTCHA_SECRET_KEY", None)

    result = asyncio.run(recaptcha.verify_recaptcha(token="any-token"))

    assert result["success"] is True
    assert result["score"] == 1.0
    assert "deshabilitado" in result["warning"]


def test_verify_recaptcha_rejects_empty_token(monkeypatch):
    monkeypatch.setattr(recaptcha.settings, "RECAPTCHA_SECRET_KEY", "secret-key")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recaptcha.verify_recaptcha(token=""))

    assert exc_info.value.status_code == 400
    assert "Token de reCAPTCHA requerido" in exc_info.value.detail


def test_verify_recaptcha_returns_google_payload_on_valid_score(monkeypatch):
    monkeypatch.setattr(recaptcha.settings, "RECAPTCHA_SECRET_KEY", "secret-key")
    fake_client = _FakeAsyncClient(
        payload={"success": True, "score": 0.91, "action": "contact_form"}
    )

    monkeypatch.setattr(recaptcha.httpx, "AsyncClient", lambda timeout: fake_client)

    result = asyncio.run(recaptcha.verify_recaptcha(token="good-token", min_score=0.5))

    assert result["success"] is True
    assert result["score"] == 0.91
    assert fake_client.calls[0]["url"].endswith("/siteverify")
    assert fake_client.calls[0]["data"]["secret"] == "secret-key"
    assert fake_client.calls[0]["data"]["response"] == "good-token"


def test_verify_recaptcha_rejects_when_google_returns_unsuccessful(monkeypatch):
    monkeypatch.setattr(recaptcha.settings, "RECAPTCHA_SECRET_KEY", "secret-key")
    fake_client = _FakeAsyncClient(
        payload={"success": False, "error-codes": ["timeout-or-duplicate"]}
    )
    monkeypatch.setattr(recaptcha.httpx, "AsyncClient", lambda timeout: fake_client)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recaptcha.verify_recaptcha(token="bad-token"))

    assert exc_info.value.status_code == 400
    assert "reCAPTCHA inválido" in exc_info.value.detail


def test_verify_recaptcha_rejects_low_score(monkeypatch):
    monkeypatch.setattr(recaptcha.settings, "RECAPTCHA_SECRET_KEY", "secret-key")
    fake_client = _FakeAsyncClient(payload={"success": True, "score": 0.1})
    monkeypatch.setattr(recaptcha.httpx, "AsyncClient", lambda timeout: fake_client)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recaptcha.verify_recaptcha(token="suspicious-token", min_score=0.5))

    assert exc_info.value.status_code == 400
    assert "Verificación de seguridad fallida" in exc_info.value.detail


def test_verify_recaptcha_handles_timeout(monkeypatch):
    monkeypatch.setattr(recaptcha.settings, "RECAPTCHA_SECRET_KEY", "secret-key")
    fake_client = _FakeAsyncClient(post_error=httpx.TimeoutException("request timed out"))
    monkeypatch.setattr(recaptcha.httpx, "AsyncClient", lambda timeout: fake_client)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recaptcha.verify_recaptcha(token="token"))

    assert exc_info.value.status_code == 503
    assert "temporalmente no disponible" in exc_info.value.detail


def test_verify_recaptcha_handles_request_error(monkeypatch):
    monkeypatch.setattr(recaptcha.settings, "RECAPTCHA_SECRET_KEY", "secret-key")
    request = httpx.Request("POST", "https://www.google.com/recaptcha/api/siteverify")
    fake_client = _FakeAsyncClient(
        post_error=httpx.RequestError("network down", request=request)
    )
    monkeypatch.setattr(recaptcha.httpx, "AsyncClient", lambda timeout: fake_client)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recaptcha.verify_recaptcha(token="token"))

    assert exc_info.value.status_code == 503
    assert "Error al verificar reCAPTCHA" in exc_info.value.detail


def test_verify_recaptcha_wraps_unexpected_errors(monkeypatch):
    monkeypatch.setattr(recaptcha.settings, "RECAPTCHA_SECRET_KEY", "secret-key")

    class _BrokenResponse:
        def json(self):
            raise RuntimeError("invalid JSON")

    class _ClientReturningBrokenResponse(_FakeAsyncClient):
        async def post(self, url, data):
            self.calls.append({"url": url, "data": data})
            return _BrokenResponse()

    fake_client = _ClientReturningBrokenResponse()
    monkeypatch.setattr(recaptcha.httpx, "AsyncClient", lambda timeout: fake_client)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(recaptcha.verify_recaptcha(token="token"))

    assert exc_info.value.status_code == 500
    assert "Error interno al verificar reCAPTCHA" in exc_info.value.detail

"""Tests para app.services.kore.KoreService (async httpx sin red real)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.kore import (
    KoreAuthError,
    KoreService,
    KoreSmsError,
    kore_service,
)


def _async_cm_mock(inner_client):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner_client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def test_is_configured_false_when_missing_credentials(monkeypatch):
    svc = KoreService()
    monkeypatch.setattr(svc, "client_id", None)
    assert svc.is_configured() is False


def test_authenticate_success(monkeypatch):
    svc = KoreService()
    monkeypatch.setattr(svc, "client_id", "id")
    monkeypatch.setattr(svc, "client_secret", "sec")
    monkeypatch.setattr(svc, "auth_url", "https://auth.example/oauth")
    monkeypatch.setattr(svc, "sms_url", "https://sms.example/send")

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "access_token": "tok",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "x",
    }

    inner = MagicMock()
    inner.post = AsyncMock(return_value=resp)

    async def run():
        with patch(
            "app.services.kore.httpx.AsyncClient",
            return_value=_async_cm_mock(inner),
        ):
            return await svc.authenticate()

    result = asyncio.run(run())

    assert result.access_token == "tok"
    assert svc._cached_token == "tok"


def test_authenticate_raises_when_not_configured():
    svc = KoreService()
    with patch.object(svc, "is_configured", return_value=False):
        with pytest.raises(KoreAuthError, match="no configurado"):
            asyncio.run(svc.authenticate())


def test_authenticate_raises_on_http_error(monkeypatch):
    svc = KoreService()
    monkeypatch.setattr(svc, "client_id", "id")
    monkeypatch.setattr(svc, "client_secret", "sec")
    monkeypatch.setattr(svc, "auth_url", "https://auth.example/oauth")
    monkeypatch.setattr(svc, "sms_url", "https://sms.example/send")

    resp = MagicMock()
    resp.status_code = 401
    resp.text = "unauthorized"

    inner = MagicMock()
    inner.post = AsyncMock(return_value=resp)

    async def run():
        with patch(
            "app.services.kore.httpx.AsyncClient",
            return_value=_async_cm_mock(inner),
        ):
            await svc.authenticate()

    with pytest.raises(KoreAuthError, match="401"):
        asyncio.run(run())


def test_send_sms_command_success(monkeypatch):
    svc = KoreService()
    monkeypatch.setattr(svc, "client_id", "id")
    monkeypatch.setattr(svc, "client_secret", "sec")
    monkeypatch.setattr(svc, "auth_url", "https://auth.example/oauth")
    monkeypatch.setattr(svc, "sms_url", "https://sms.example/send")
    svc._cached_token = "cached"

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True}

    inner = MagicMock()
    inner.post = AsyncMock(return_value=resp)

    async def run():
        with patch(
            "app.services.kore.httpx.AsyncClient",
            return_value=_async_cm_mock(inner),
        ):
            return await svc.send_sms_command("SIM123", "CMD")

    out = asyncio.run(run())

    assert out.success is True


def test_send_sms_command_raises_when_not_configured():
    svc = KoreService()

    async def run():
        with patch.object(svc, "is_configured", return_value=False):
            await svc.send_sms_command("SIM", "X")

    with pytest.raises(KoreSmsError, match="no configurado"):
        asyncio.run(run())


def test_singleton_instance_exists():
    assert isinstance(kore_service, KoreService)

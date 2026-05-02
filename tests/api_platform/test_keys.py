"""Unit tests for API key creation and revoke flow."""

import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.api_platform.models.api_key import ApiKey
from app.api.v1.endpoints.api_platform.schemas.keys import ApiKeyCreate, ApiKeyUpdate
from app.api.v1.endpoints.api_platform.services.keys import (
    ApiKeyService,
    _generate_api_key,
)


# ---------------------------------------------------------------------------
# Key generation helpers
# ---------------------------------------------------------------------------


def test_generate_api_key_format():
    full_key, prefix, key_hash = _generate_api_key()
    assert full_key.startswith("orion_live_")
    assert prefix == full_key[:20]
    assert key_hash == hashlib.sha256(full_key.encode()).hexdigest()


def test_generate_api_key_uniqueness():
    keys = {_generate_api_key()[0] for _ in range(20)}
    assert len(keys) == 20, "All generated keys must be unique"


# ---------------------------------------------------------------------------
# ApiKeyService.create
# ---------------------------------------------------------------------------


def _make_saved_key(org_id, product_id, name) -> ApiKey:
    key = ApiKey(
        id=uuid4(),
        organization_id=org_id,
        product_id=product_id,
        name=name,
        key_hash="fakehash",
        prefix="orion_live_xxxx",
        status="ACTIVE",
    )
    return key


def test_create_api_key_returns_model_and_full_key():
    db = MagicMock()
    org_id = uuid4()
    product_id = uuid4()
    data = ApiKeyCreate(product_id=product_id, name="test key")

    saved = _make_saved_key(org_id, product_id, "test key")

    with patch(
        "app.api.v1.endpoints.api_platform.services.keys.ApiKeyRepository.create",
        return_value=saved,
    ):
        result_key, full_key = ApiKeyService.create(db, org_id, data)

    assert result_key.organization_id == org_id
    assert result_key.product_id == product_id
    assert result_key.status == "ACTIVE"
    assert full_key.startswith("orion_live_")


def test_create_api_key_never_stores_plaintext():
    db = MagicMock()
    org_id = uuid4()
    product_id = uuid4()
    data = ApiKeyCreate(product_id=product_id, name="secure key")

    captured = {}

    def fake_create(db, key: ApiKey):
        captured["key"] = key
        key.id = uuid4()
        return key

    with patch(
        "app.api.v1.endpoints.api_platform.services.keys.ApiKeyRepository.create",
        side_effect=fake_create,
    ):
        _, full_key = ApiKeyService.create(db, org_id, data)

    stored_key = captured["key"]
    assert stored_key.key_hash != full_key
    assert full_key not in (stored_key.prefix, stored_key.key_hash)
    assert stored_key.key_hash == hashlib.sha256(full_key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# ApiKeyService.revoke
# ---------------------------------------------------------------------------


def test_revoke_sets_status_and_timestamp():
    db = MagicMock()
    org_id = uuid4()
    key_id = uuid4()

    existing = _make_saved_key(org_id, uuid4(), "my key")
    existing.id = key_id
    existing.status = "ACTIVE"
    existing.revoked_at = None

    with (
        patch(
            "app.api.v1.endpoints.api_platform.services.keys.ApiKeyRepository.get_by_id",
            return_value=existing,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.keys.ApiKeyRepository.update",
            side_effect=lambda db, k: k,
        ),
    ):
        result = ApiKeyService.revoke(db, key_id, org_id)

    assert result.status == "REVOKED"
    assert result.revoked_at is not None
    assert result.revoked_at.tzinfo is not None


def test_revoke_already_revoked_raises_409():
    db = MagicMock()
    org_id = uuid4()
    key_id = uuid4()

    existing = _make_saved_key(org_id, uuid4(), "revoked key")
    existing.id = key_id
    existing.status = "REVOKED"

    with patch(
        "app.api.v1.endpoints.api_platform.services.keys.ApiKeyRepository.get_by_id",
        return_value=existing,
    ):
        with pytest.raises(HTTPException) as exc_info:
            ApiKeyService.revoke(db, key_id, org_id)

    assert exc_info.value.status_code == 409


def test_revoke_not_found_raises_404():
    db = MagicMock()
    with patch(
        "app.api.v1.endpoints.api_platform.services.keys.ApiKeyRepository.get_by_id",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            ApiKeyService.revoke(db, uuid4(), uuid4())

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# ApiKeyService.update
# ---------------------------------------------------------------------------


def test_update_api_key_name():
    db = MagicMock()
    org_id = uuid4()
    key_id = uuid4()

    existing = _make_saved_key(org_id, uuid4(), "old name")
    existing.id = key_id

    with (
        patch(
            "app.api.v1.endpoints.api_platform.services.keys.ApiKeyRepository.get_by_id",
            return_value=existing,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.keys.ApiKeyRepository.update",
            side_effect=lambda db, k: k,
        ),
    ):
        result = ApiKeyService.update(db, key_id, org_id, ApiKeyUpdate(name="new name"))

    assert result.name == "new name"


def test_update_api_key_not_found_raises_404():
    db = MagicMock()
    with patch(
        "app.api.v1.endpoints.api_platform.services.keys.ApiKeyRepository.get_by_id",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            ApiKeyService.update(db, uuid4(), uuid4(), ApiKeyUpdate(name="x"))

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Cross-org access prevention
# ---------------------------------------------------------------------------


def test_get_key_wrong_org_raises_404():
    db = MagicMock()
    with patch(
        "app.api.v1.endpoints.api_platform.services.keys.ApiKeyRepository.get_by_id",
        return_value=None,
    ):
        with pytest.raises(HTTPException) as exc_info:
            ApiKeyService.get(db, uuid4(), uuid4())

    assert exc_info.value.status_code == 404

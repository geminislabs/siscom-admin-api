"""Tests para app.services.capabilities (ResolvedCapability y CapabilityService)."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.models.capability import Capability, OrganizationCapability
from app.services.capabilities import (
    CapabilityService,
    DEFAULT_CAPABILITIES,
    ResolvedCapability,
    get_capability_for_client,
    has_capability_for_client,
    validate_limit_for_client,
)


def test_resolved_capability_as_int_bool_and_strings():
    assert ResolvedCapability("c", True, "plan").as_bool() is True
    assert ResolvedCapability("c", True, "plan").as_int() == 1
    assert ResolvedCapability("c", 42, "plan").as_int() == 42
    assert ResolvedCapability("c", "yes", "default").as_bool() is True
    assert ResolvedCapability("c", None, "default").as_int() == 0


def test_validate_limit_zero_or_negative_means_unlimited():
    db = MagicMock()
    org_id = uuid4()

    with patch.object(CapabilityService, "get_limit", return_value=0):
        assert CapabilityService.validate_limit(db, org_id, "max_devices", 999) is True


def test_validate_limit_checks_ceiling():
    db = MagicMock()
    org_id = uuid4()

    with patch.object(CapabilityService, "get_limit", return_value=5):
        assert CapabilityService.validate_limit(db, org_id, "max_devices", 4) is True
        assert CapabilityService.validate_limit(db, org_id, "max_devices", 5) is False


def test_get_capability_unknown_code_uses_default_without_capability_row():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    org_id = uuid4()

    res = CapabilityService.get_capability(db, org_id, "max_devices")
    assert res.source == "default"
    assert res.value == DEFAULT_CAPABILITIES["max_devices"]


def test_get_capability_prefers_organization_override(monkeypatch):
    db = MagicMock()
    org_id = uuid4()
    cap_id = uuid4()

    capability_row = MagicMock(spec=Capability)
    capability_row.id = cap_id
    capability_row.code = "ai_features"

    org_ov = MagicMock(spec=OrganizationCapability)
    org_ov.get_value.return_value = True
    org_ov.expires_at = None
    org_ov.is_expired = MagicMock(return_value=False)

    def query_side_effect(model):
        q = MagicMock()
        if model is Capability:
            q.filter.return_value.first.return_value = capability_row
        elif model is OrganizationCapability:
            q.filter.return_value.first.return_value = org_ov
        else:
            raise AssertionError(model)
        return q

    db.query.side_effect = query_side_effect

    res = CapabilityService.get_capability(db, org_id, "ai_features")
    assert res.source == "organization"
    assert res.value is True


def test_get_capabilities_summary_splits_limits_and_features():
    db = MagicMock()

    caps = {
        "max_devices": ResolvedCapability(
            code="max_devices", value=10, source="plan"
        ),
        "ai_features": ResolvedCapability(
            code="ai_features", value=True, source="organization"
        ),
        "notes": ResolvedCapability(code="notes", value="vip", source="default"),
    }

    with patch.object(CapabilityService, "get_all_capabilities", return_value=caps):
        summary = CapabilityService.get_capabilities_summary(db, uuid4())

    assert summary["limits"]["max_devices"] == 10
    assert summary["features"]["ai_features"] is True
    assert summary["features"]["notes"] == "vip"


def test_deprecated_client_aliases_delegate():
    db = MagicMock()
    cid = uuid4()

    with patch(
        "app.services.capabilities.get_capability",
        return_value=ResolvedCapability("x", 1, "default"),
    ) as m1:
        assert get_capability_for_client(db, cid, "max_devices").value == 1
        m1.assert_called_once_with(db, cid, "max_devices")

    with patch(
        "app.services.capabilities.has_capability",
        return_value=True,
    ) as m2:
        assert has_capability_for_client(db, cid, "ai_features") is True
        m2.assert_called_once_with(db, cid, "ai_features")

    with patch(
        "app.services.capabilities.validate_limit",
        return_value=True,
    ) as m3:
        assert validate_limit_for_client(db, cid, "max_devices", 3) is True
        m3.assert_called_once_with(db, cid, "max_devices", 3)

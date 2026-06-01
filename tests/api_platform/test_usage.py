"""Unit tests for usage summary service."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.api.v1.endpoints.api_platform.schemas.usage import UsageSummary
from app.api.v1.endpoints.api_platform.services.usage import UsageService


def test_usage_summary_happy_path():
    db = MagicMock()
    org_id = uuid4()

    with (
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.ApiKeyRepository.count_active",
            return_value=3,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.UsageRepository.get_requests_today",
            return_value=500,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.UsageRepository.get_errors_today",
            return_value=25,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.UsageRepository.get_requests_month",
            return_value=12000,
        ),
    ):
        result = UsageService.get_summary(db, org_id)

    assert isinstance(result, UsageSummary)
    assert result.active_keys == 3
    assert result.requests_today == 500
    assert result.requests_month == 12000
    assert result.error_rate == round(25 / 500, 4)


def test_usage_summary_zero_requests_no_division_error():
    db = MagicMock()
    org_id = uuid4()

    with (
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.ApiKeyRepository.count_active",
            return_value=0,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.UsageRepository.get_requests_today",
            return_value=0,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.UsageRepository.get_errors_today",
            return_value=0,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.UsageRepository.get_requests_month",
            return_value=0,
        ),
    ):
        result = UsageService.get_summary(db, org_id)

    assert result.error_rate == 0.0
    assert result.active_keys == 0


def test_usage_summary_full_error_rate():
    db = MagicMock()
    org_id = uuid4()

    with (
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.ApiKeyRepository.count_active",
            return_value=1,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.UsageRepository.get_requests_today",
            return_value=100,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.UsageRepository.get_errors_today",
            return_value=100,
        ),
        patch(
            "app.api.v1.endpoints.api_platform.services.usage.UsageRepository.get_requests_month",
            return_value=2000,
        ),
    ):
        result = UsageService.get_summary(db, org_id)

    assert result.error_rate == 1.0

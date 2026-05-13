"""
Tests unitarios para app.services.sns (cliente SNS singleton, endpoints y recuperación).

Usan mocks de boto3/botocore; no llaman a AWS reales.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import app.services.sns as sns_module
from app.services.sns import (
    _can_recreate_endpoint,
    _extract_arn_from_error,
    _platform_application_arn,
    create_endpoint,
    endpoint_is_valid,
    get_or_recreate_endpoint,
    get_sns_client,
    update_endpoint,
)


@pytest.fixture(autouse=True)
def reset_sns_client_singleton():
    """Evita que un test reutilice el cliente mockeado de otro."""
    sns_module._sns_client = None
    yield
    sns_module._sns_client = None


def _client_error(code: str, message: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "TestOperation",
    )


def test_get_sns_client_raises_when_region_missing(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "")
    with pytest.raises(RuntimeError, match="AWS_REGION no configurada"):
        get_sns_client()


def test_get_sns_client_raises_when_region_only_whitespace(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "   \t  ")
    with pytest.raises(RuntimeError, match="AWS_REGION no configurada"):
        get_sns_client()


def test_get_sns_client_creates_boto_client_with_region(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(sns_module.settings, "AWS_ACCESS_KEY_ID", None)
    monkeypatch.setattr(sns_module.settings, "AWS_SECRET_ACCESS_KEY", None)

    mock_sns = MagicMock()
    with patch("app.services.sns.boto3.client", return_value=mock_sns) as m_client:
        c1 = get_sns_client()
        c2 = get_sns_client()
    assert c1 is c2 is mock_sns
    m_client.assert_called_once_with("sns", region_name="us-east-1")


def test_get_sns_client_passes_explicit_credentials_when_configured(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "eu-west-1")
    monkeypatch.setattr(sns_module.settings, "AWS_ACCESS_KEY_ID", "AKIATEST")
    monkeypatch.setattr(sns_module.settings, "AWS_SECRET_ACCESS_KEY", "secret-key")

    mock_sns = MagicMock()
    with patch("app.services.sns.boto3.client", return_value=mock_sns) as m_client:
        get_sns_client()
        m_client.assert_called_once_with(
            "sns",
            region_name="eu-west-1",
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret-key",
        )


def test_get_sns_client_strips_region(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "  sa-east-1  ")
    monkeypatch.setattr(sns_module.settings, "AWS_ACCESS_KEY_ID", None)
    monkeypatch.setattr(sns_module.settings, "AWS_SECRET_ACCESS_KEY", None)

    mock_sns = MagicMock()
    with patch("app.services.sns.boto3.client", return_value=mock_sns) as m_client:
        get_sns_client()
        m_client.assert_called_once_with("sns", region_name="sa-east-1")


def test_platform_arn_ios(monkeypatch):
    arn = "arn:aws:sns:us-east-1:1:app/APNS/my-ios"
    monkeypatch.setattr(sns_module.settings, "SNS_PLATFORM_APPLICATION_ARN_IOS", arn)
    assert _platform_application_arn("ios") == arn


def test_platform_arn_android(monkeypatch):
    arn = "arn:aws:sns:us-east-1:1:app/GCM/my-android"
    monkeypatch.setattr(
        sns_module.settings, "SNS_PLATFORM_APPLICATION_ARN_ANDROID", arn
    )
    assert _platform_application_arn("android") == arn


def test_platform_arn_invalid_platform():
    with pytest.raises(ValueError, match="Invalid platform"):
        _platform_application_arn("web")


def test_platform_arn_missing_configuration_ios(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "SNS_PLATFORM_APPLICATION_ARN_IOS", None)
    with pytest.raises(ValueError, match="SNS platform ARN no configurado"):
        _platform_application_arn("ios")


def test_platform_arn_missing_configuration_android(monkeypatch):
    monkeypatch.setattr(
        sns_module.settings, "SNS_PLATFORM_APPLICATION_ARN_ANDROID", ""
    )
    with pytest.raises(ValueError, match="SNS platform ARN no configurado"):
        _platform_application_arn("android")


def test_extract_arn_from_error_finds_arn():
    msg = (
        "Endpoint already exists; existing arn:aws:sns:us-east-1:999:endpoint/foo/bar "
        "must be reused"
    )
    assert (
        _extract_arn_from_error(msg)
        == "arn:aws:sns:us-east-1:999:endpoint/foo/bar"
    )


def test_extract_arn_from_error_returns_none_when_no_arn():
    assert _extract_arn_from_error("no arn here") is None


def test_create_endpoint_returns_endpoint_arn(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "arn:aws:sns:us-east-1:1:app/APNS/x",
    )

    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.return_value = {
        "EndpointArn": "arn:aws:sns:us-east-1:1:endpoint/APNS/foo"
    }
    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        arn = create_endpoint("device-token-xyz", "ios")

    assert arn == "arn:aws:sns:us-east-1:1:endpoint/APNS/foo"
    mock_sns.create_platform_endpoint.assert_called_once_with(
        PlatformApplicationArn="arn:aws:sns:us-east-1:1:app/APNS/x",
        Token="device-token-xyz",
    )


def test_create_endpoint_reuses_arn_on_duplicate_invalid_parameter(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_ANDROID",
        "arn:aws:sns:us-east-1:1:app/GCM/x",
    )

    existing = "arn:aws:sns:us-east-1:1:endpoint/GCM/existing"
    exc = ClientError(
        {
            "Error": {
                "Code": "InvalidParameter",
                "Message": f"Endpoint already exists with the same Token; ARN is {existing}",
            }
        },
        "CreatePlatformEndpoint",
    )

    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.side_effect = exc

    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        assert create_endpoint("same-token", "android") == existing


def test_create_endpoint_duplicate_logs_reuse(caplog, monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_ANDROID",
        "arn:aws:sns:us-east-1:1:app/GCM/x",
    )

    existing = "arn:aws:sns:us-east-1:1:endpoint/GCM/existing"
    exc = ClientError(
        {
            "Error": {
                "Code": "InvalidParameter",
                "Message": f"already exists token dup arn:aws:sns:us-east-1:1:endpoint/GCM/existing",
            }
        },
        "CreatePlatformEndpoint",
    )

    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.side_effect = exc

    with caplog.at_level(logging.INFO):
        with patch("app.services.sns.boto3.client", return_value=mock_sns):
            create_endpoint("same-token", "android")

    assert any("reutilizando ARN" in r.message for r in caplog.records)


def test_create_endpoint_raises_duplicate_when_arn_not_extractable(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "arn:aws:sns:us-east-1:1:app/APNS/x",
    )

    exc = ClientError(
        {
            "Error": {
                "Code": "InvalidParameter",
                "Message": "already exists but message without parsable arn:aws pattern here",
            }
        },
        "CreatePlatformEndpoint",
    )

    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.side_effect = exc

    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        with pytest.raises(ClientError):
            create_endpoint("tok", "ios")


def test_create_endpoint_raises_other_client_errors(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "arn:aws:sns:us-east-1:1:app/APNS/x",
    )

    exc = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "not allowed"}},
        "CreatePlatformEndpoint",
    )
    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.side_effect = exc

    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        with pytest.raises(ClientError) as ei:
            create_endpoint("tok", "ios")
        assert ei.value.response["Error"]["Code"] == "AccessDenied"


@pytest.mark.parametrize(
    "enabled_raw,expected",
    [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("false", False),
        ("anything", False),
    ],
)
def test_endpoint_is_valid_reflects_enabled_attribute(
    monkeypatch, enabled_raw, expected
):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    mock_sns = MagicMock()
    mock_sns.get_endpoint_attributes.return_value = {
        "Attributes": {"Enabled": enabled_raw}
    }
    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        assert endpoint_is_valid("arn:end") is expected


def test_endpoint_is_valid_false_when_enabled_attribute_missing(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    mock_sns = MagicMock()
    mock_sns.get_endpoint_attributes.return_value = {"Attributes": {}}
    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        assert endpoint_is_valid("arn:any") is False


def test_endpoint_is_valid_false_when_client_errors(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    mock_sns = MagicMock()
    mock_sns.get_endpoint_attributes.side_effect = _client_error(
        "NotFound", "endpoint gone"
    )
    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        assert endpoint_is_valid("arn:missing") is False


def test_can_recreate_true_for_not_found_codes():
    assert _can_recreate_endpoint(_client_error("NotFound", "x")) is True
    assert _can_recreate_endpoint(_client_error("NotFoundException", "x")) is True


def test_can_recreate_true_invalid_parameter_does_not_exist():
    exc = _client_error("InvalidParameter", "Endpoint does not exist anymore")
    assert _can_recreate_endpoint(exc) is True


def test_can_recreate_true_invalid_parameter_not_found_phrase():
    exc = _client_error("InvalidParameter", "was not found in sns")
    assert _can_recreate_endpoint(exc) is True


def test_can_recreate_true_invalid_parameter_endpoint_and_exist_substrings():
    """Coincide con la condición ('endpoint' in message and 'exist' in message)."""
    exc = _client_error(
        "InvalidParameter",
        "The endpoint foobar does not exist",
    )
    assert _can_recreate_endpoint(exc) is True


def test_can_recreate_false_for_other_errors():
    assert _can_recreate_endpoint(_client_error("Throttling", "slow down")) is False
    assert (
        _can_recreate_endpoint(_client_error("InvalidParameter", "bad token format"))
        is False
    )


def test_update_endpoint_sets_token_and_enabled(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    mock_sns = MagicMock()
    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        update_endpoint("arn:aws:sns:e:a:e/e", "new-device-token")

    mock_sns.set_endpoint_attributes.assert_called_once_with(
        EndpointArn="arn:aws:sns:e:a:e/e",
        Attributes={"Token": "new-device-token", "Enabled": "true"},
    )


def test_get_or_recreate_without_arn_calls_create(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "arn:aws:sns:us-east-1:1:app/APNS/x",
    )

    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.return_value = {
        "EndpointArn": "arn:aws:sns:us-east-1:1:endpoint/APNS/new"
    }

    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        arn, recreated = get_or_recreate_endpoint("tok", "ios", None)

    assert arn == "arn:aws:sns:us-east-1:1:endpoint/APNS/new"
    assert recreated is True
    mock_sns.create_platform_endpoint.assert_called_once()


def test_get_or_recreate_empty_arn_skips_update(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "arn:aws:sns:us-east-1:1:app/APNS/x",
    )

    mock_sns = MagicMock()
    mock_sns.create_platform_endpoint.return_value = {
        "EndpointArn": "arn:aws:sns:us-east-1:1:endpoint/APNS/created"
    }

    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        arn, recreated = get_or_recreate_endpoint("tok", "ios", "")

    assert recreated is True
    mock_sns.set_endpoint_attributes.assert_not_called()


def test_get_or_recreate_updates_existing_when_arn_present(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "arn:aws:sns:us-east-1:1:app/APNS/x",
    )

    mock_sns = MagicMock()
    ep = "arn:aws:sns:us-east-1:1:endpoint/APNS/existing"

    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        out_arn, recreated = get_or_recreate_endpoint("tok", "ios", ep)

    assert out_arn == ep
    assert recreated is False
    mock_sns.set_endpoint_attributes.assert_called_once()
    mock_sns.create_platform_endpoint.assert_not_called()


def test_get_or_recreate_raises_when_update_fails_non_recoverable(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "arn:aws:sns:us-east-1:1:app/APNS/x",
    )

    mock_sns = MagicMock()
    mock_sns.set_endpoint_attributes.side_effect = _client_error(
        "InvalidParameter",
        "invalid token format",
    )

    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        with pytest.raises(ClientError):
            get_or_recreate_endpoint(
                "tok",
                "ios",
                "arn:aws:sns:us-east-1:1:endpoint/APNS/old",
            )


def test_get_or_recreate_recreates_when_update_signals_missing_endpoint(monkeypatch):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "arn:aws:sns:us-east-1:1:app/APNS/x",
    )

    mock_sns = MagicMock()
    mock_sns.set_endpoint_attributes.side_effect = _client_error(
        "NotFound",
        "endpoint missing",
    )
    mock_sns.create_platform_endpoint.return_value = {
        "EndpointArn": "arn:aws:sns:us-east-1:1:endpoint/APNS/recreated"
    }

    with patch("app.services.sns.boto3.client", return_value=mock_sns):
        arn, recreated = get_or_recreate_endpoint(
            "tok",
            "ios",
            "arn:aws:sns:us-east-1:1:endpoint/APNS/stale",
        )

    assert arn == "arn:aws:sns:us-east-1:1:endpoint/APNS/recreated"
    assert recreated is True
    mock_sns.create_platform_endpoint.assert_called_once()


def test_get_or_recreate_logs_warning_when_falling_back_to_create(monkeypatch, caplog):
    monkeypatch.setattr(sns_module.settings, "AWS_REGION", "us-east-1")
    monkeypatch.setattr(
        sns_module.settings,
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "arn:aws:sns:us-east-1:1:app/APNS/x",
    )

    mock_sns = MagicMock()
    mock_sns.set_endpoint_attributes.side_effect = _client_error(
        "NotFound",
        "gone",
    )
    mock_sns.create_platform_endpoint.return_value = {
        "EndpointArn": "arn:aws:sns:us-east-1:1:endpoint/APNS/new"
    }

    with caplog.at_level(logging.WARNING):
        with patch("app.services.sns.boto3.client", return_value=mock_sns):
            get_or_recreate_endpoint(
                "tok",
                "ios",
                "arn:aws:sns:us-east-1:1:endpoint/APNS/old",
            )

    assert any(
        "No se pudo actualizar endpoint SNS" in r.message for r in caplog.records
    )

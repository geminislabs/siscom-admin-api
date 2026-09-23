"""Tests unitarios de observabilidad. Sin Collector."""

import io
import json
import logging
from types import SimpleNamespace

from app.observability.init import (
    get_tracer_provider,
    reset_telemetry_for_tests,
    setup_telemetry,
    telemetry_enabled,
)
from app.observability.logging import (
    JSONFormatter,
    configure_json_logging,
    reset_logging_for_tests,
    scrub_value,
)


def _settings(**overrides):
    base = {
        "OTLP_ENDPOINT": "",
        "DEPLOY_ENV": "local",
        "SERVICE_NAME": "siscom-admin-api",
        "SERVICE_VERSION": "0.1.0",
        "LOG_LEVEL": "INFO",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_setup_telemetry_empty_endpoint_is_noop():
    reset_telemetry_for_tests()
    setup_telemetry(_settings(OTLP_ENDPOINT=""))
    assert telemetry_enabled() is False
    assert get_tracer_provider() is None


def test_setup_telemetry_empty_endpoint_does_not_raise():
    reset_telemetry_for_tests()
    setup_telemetry(_settings(OTLP_ENDPOINT="   "))
    assert telemetry_enabled() is False


def test_setup_telemetry_is_idempotent():
    reset_telemetry_for_tests()
    setup_telemetry(_settings(OTLP_ENDPOINT="http://localhost:4318"))
    first = get_tracer_provider()
    assert first is not None
    setup_telemetry(_settings(OTLP_ENDPOINT="http://localhost:4318"))
    assert get_tracer_provider() is first
    reset_telemetry_for_tests()


def test_configure_json_logging_emits_required_fields():
    reset_logging_for_tests()
    configure_json_logging(_settings(), level="INFO")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        JSONFormatter(service_name="siscom-admin-api", deploy_env="local")
    )
    logger = logging.getLogger("test.observability.json")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("auth.login.success", extra={"user_id": "u-1", "method": "cognito"})
    payload = json.loads(stream.getvalue())
    assert payload["message"] == "auth.login.success"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.observability.json"
    assert "timestamp" in payload
    assert payload["service.name"] == "siscom-admin-api"
    assert payload["deployment.environment"] == "local"
    assert "trace_id" in payload
    assert "span_id" in payload
    assert "request_id" in payload
    assert payload["user_id"] == "u-1"
    assert payload["method"] == "cognito"


def test_scrubber_redacts_password_in_extra():
    assert scrub_value("password", "hunter2") == "[REDACTED]"
    assert scrub_value("user_password", "x") == "[REDACTED]"
    nested = scrub_value("payload", {"refresh_token": "abc", "ok": 1})
    assert nested["refresh_token"] == "[REDACTED]"
    assert nested["ok"] == 1

    fmt = JSONFormatter()
    rec = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="x",
        lineno=1,
        msg="auth.login.failure",
        args=(),
        exc_info=None,
    )
    rec.password = "secret-value"
    data = json.loads(fmt.format(rec))
    assert data["password"] == "[REDACTED]"

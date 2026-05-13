"""Tests para app.services.messaging.kafka_producer."""

from unittest.mock import MagicMock, patch

import pytest

import app.services.messaging.kafka_producer as kp_mod
from app.services.messaging.kafka_producer import (
    GeofencesKafkaProducer,
    RulesKafkaProducer,
    UserDevicesKafkaProducer,
)


@pytest.fixture
def kafka_settings(monkeypatch):
    monkeypatch.setattr(kp_mod.settings, "KAFKA_BROKERS", "localhost:9092")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_SECURITY_PROTOCOL", "")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_SASL_USERNAME", "")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_SASL_PASSWORD", "")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_SASL_MECHANISM", "")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_RULES_UPDATES_TOPIC", "rules-topic")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_RULES_UPDATES_GROUP_ID", "rules-group")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_USER_DEVICES_UPDATES_TOPIC", "ud-topic")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_GEOFENCES_UPDATES_TOPIC", "gf-topic")


def test_rules_build_client_config_includes_sasl_when_set(monkeypatch, kafka_settings):
    monkeypatch.setattr(kp_mod.settings, "KAFKA_SECURITY_PROTOCOL", "SASL_SSL")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_SASL_USERNAME", "user")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_SASL_PASSWORD", "pass")
    monkeypatch.setattr(kp_mod.settings, "KAFKA_SASL_MECHANISM", "PLAIN")

    prod = RulesKafkaProducer()
    cfg = prod._build_client_config()

    assert cfg["bootstrap_servers"] == ["localhost:9092"]
    assert cfg["security_protocol"] == "SASL_SSL"
    assert cfg["sasl_plain_username"] == "user"
    assert cfg["sasl_plain_password"] == "pass"
    assert cfg["sasl_mechanism"] == "PLAIN"


def test_rules_publish_returns_false_when_kafka_not_installed(monkeypatch, kafka_settings):
    monkeypatch.setattr(kp_mod, "KafkaProducer", None)

    prod = RulesKafkaProducer()
    assert prod.publish_rule_update({"operation": "upsert", "rule_id": "r1"}) is False


def test_rules_publish_success_path(monkeypatch, kafka_settings):
    future = MagicMock()
    future.get.return_value = None

    mock_inner = MagicMock()
    mock_inner.send.return_value = future

    kafka_cls = MagicMock(return_value=mock_inner)

    monkeypatch.setattr(kp_mod, "KafkaProducer", kafka_cls)

    prod = RulesKafkaProducer()
    ok = prod.publish_rule_update({"operation": "upsert"}, key="k1")

    assert ok is True
    mock_inner.send.assert_called_once()
    mock_inner.flush.assert_called_once()


def test_rules_close_noops_when_never_created(monkeypatch, kafka_settings):
    prod = RulesKafkaProducer()
    prod.close()


def test_user_devices_publish_failure_returns_false(monkeypatch, kafka_settings):
    monkeypatch.setattr(kp_mod, "KafkaProducer", MagicMock(side_effect=RuntimeError("boom")))

    prod = UserDevicesKafkaProducer()
    assert prod.publish_update({"type": "link"}) is False


def test_geofences_close_handles_flush_errors(monkeypatch, kafka_settings):
    bad = MagicMock()
    bad.flush.side_effect = OSError("x")

    prod = GeofencesKafkaProducer()
    prod._producer = bad

    prod.close()

    assert prod._producer is None


def test_key_serializer_handles_none():
    prod = RulesKafkaProducer()
    cfg = prod._build_client_config()
    ser = cfg["key_serializer"]
    assert ser(None) is None

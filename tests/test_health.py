"""Tests para app.services.health.check_kafka_accessibility."""

from unittest.mock import MagicMock, patch

import app.services.health as health_mod


def test_check_kafka_returns_false_when_kafka_import_missing(monkeypatch):
    monkeypatch.setattr(health_mod, "KafkaProducer", None)

    assert health_mod.check_kafka_accessibility() is False


def test_check_kafka_returns_false_when_no_brokers(monkeypatch):
    monkeypatch.setattr(health_mod, "KafkaProducer", MagicMock())

    monkeypatch.setattr(health_mod.settings, "KAFKA_BROKERS", ", , ")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SECURITY_PROTOCOL", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_USERNAME", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_PASSWORD", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_MECHANISM", "")

    assert health_mod.check_kafka_accessibility() is False


def test_check_kafka_returns_true_when_producer_ok(monkeypatch):
    prod = MagicMock()

    kafka_cls = MagicMock(return_value=prod)

    monkeypatch.setattr(health_mod, "KafkaProducer", kafka_cls)
    monkeypatch.setattr(health_mod.settings, "KAFKA_BROKERS", "localhost:9092")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SECURITY_PROTOCOL", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_USERNAME", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_PASSWORD", "")
    monkeypatch.setattr(health_mod.settings, "KAFKA_SASL_MECHANISM", "")

    assert health_mod.check_kafka_accessibility() is True

    prod.close.assert_called_once()


def test_check_kafka_returns_false_when_kafka_raises(monkeypatch):
    monkeypatch.setattr(
        health_mod,
        "KafkaProducer",
        MagicMock(side_effect=RuntimeError("broker down")),
    )
    monkeypatch.setattr(health_mod.settings, "KAFKA_BROKERS", "localhost:9092")

    assert health_mod.check_kafka_accessibility() is False

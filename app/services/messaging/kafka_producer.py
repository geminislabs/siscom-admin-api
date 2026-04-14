import importlib
import json
import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    kafka_module = importlib.import_module("kafka")
    KafkaProducer = kafka_module.KafkaProducer
except (
    Exception
):  # pragma: no cover - import guard for environments without kafka client
    KafkaProducer = None


class RulesKafkaProducer:
    """Producer reusable para publicar cambios de reglas en Kafka."""

    def __init__(self) -> None:
        self.topic = settings.KAFKA_RULES_UPDATES_TOPIC
        self.group_id = settings.KAFKA_RULES_UPDATES_GROUP_ID
        self.brokers = [
            broker.strip()
            for broker in settings.KAFKA_BROKERS.split(",")
            if broker.strip()
        ]
        self.security_protocol = settings.KAFKA_SECURITY_PROTOCOL
        self.sasl_username = settings.KAFKA_SASL_USERNAME
        self.sasl_password = settings.KAFKA_SASL_PASSWORD
        self.sasl_mechanism = settings.KAFKA_SASL_MECHANISM
        self._producer: Optional[Any] = None

    def _build_client_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "bootstrap_servers": self.brokers,
            "acks": "all",
            "retries": 0,
            "request_timeout_ms": 3000,
            "max_block_ms": 3000,
            "api_version_auto_timeout_ms": 2000,
            "value_serializer": lambda value: json.dumps(
                value, ensure_ascii=False
            ).encode("utf-8"),
            "key_serializer": lambda value: value.encode("utf-8") if value else None,
        }

        if self.security_protocol:
            config["security_protocol"] = self.security_protocol

        if self.sasl_username:
            config["sasl_plain_username"] = self.sasl_username

        if self.sasl_password:
            config["sasl_plain_password"] = self.sasl_password

        if self.sasl_mechanism:
            config["sasl_mechanism"] = self.sasl_mechanism

        return config

    def _get_or_create(self):
        if self._producer is not None:
            return self._producer

        if KafkaProducer is None:
            logger.error(
                "[KAFKA RULES] Cliente kafka-python no disponible. "
                "Instala dependencia para habilitar publicaciones.",
                extra={
                    "extra_data": {
                        "topic": self.topic,
                        "brokers": self.brokers,
                    }
                },
            )
            return None

        if not self.brokers:
            logger.error(
                "[KAFKA RULES] No hay brokers configurados; se omite publicacion.",
                extra={"extra_data": {"topic": self.topic}},
            )
            return None

        try:
            self._producer = KafkaProducer(**self._build_client_config())
            return self._producer
        except Exception:
            logger.exception(
                "[KAFKA RULES] Error inicializando producer.",
                extra={
                    "extra_data": {
                        "topic": self.topic,
                        "brokers": self.brokers,
                        "security_protocol": self.security_protocol,
                        "group_id": self.group_id,
                    }
                },
            )
            return None

    def publish_rule_update(
        self, payload: dict[str, Any], key: Optional[str] = None
    ) -> bool:
        producer = self._get_or_create()
        if producer is None:
            return False

        try:
            logger.info(
                f"Publishing rule update: {json.dumps(payload, ensure_ascii=False)}",
                extra={
                    "extra_data": {
                        "topic": self.topic,
                        "key": key,
                        "payload": payload,
                    }
                },
            )
            future = producer.send(self.topic, key=key, value=payload)
            future.get(timeout=3)
            producer.flush(timeout=3)
            return True
        except Exception:
            logger.exception(
                "[KAFKA RULES] Error publicando evento de regla.",
                extra={
                    "extra_data": {
                        "topic": self.topic,
                        "key": key,
                        "operation": payload.get("operation"),
                        "rule_id": payload.get("rule_id")
                        or payload.get("rule", {}).get("id"),
                        "group_id": self.group_id,
                    }
                },
            )
            return False

    def close(self) -> None:
        if self._producer is None:
            return

        try:
            self._producer.flush(timeout=3)
            self._producer.close(timeout=3)
        except Exception:
            logger.exception("[KAFKA RULES] Error cerrando producer.")
        finally:
            self._producer = None


class UserDevicesKafkaProducer:
    """Producer reusable para publicar cambios de user devices en Kafka."""

    def __init__(self) -> None:
        self.topic = settings.KAFKA_USER_DEVICES_UPDATES_TOPIC
        self.brokers = [
            broker.strip()
            for broker in settings.KAFKA_BROKERS.split(",")
            if broker.strip()
        ]
        self.security_protocol = settings.KAFKA_SECURITY_PROTOCOL
        self.sasl_username = settings.KAFKA_SASL_USERNAME
        self.sasl_password = settings.KAFKA_SASL_PASSWORD
        self.sasl_mechanism = settings.KAFKA_SASL_MECHANISM
        self._producer: Optional[Any] = None

    def _build_client_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "bootstrap_servers": self.brokers,
            "acks": "all",
            "retries": 0,
            "request_timeout_ms": 3000,
            "max_block_ms": 3000,
            "api_version_auto_timeout_ms": 2000,
            "value_serializer": lambda value: json.dumps(
                value, ensure_ascii=False
            ).encode("utf-8"),
            "key_serializer": lambda value: value.encode("utf-8") if value else None,
        }

        if self.security_protocol:
            config["security_protocol"] = self.security_protocol

        if self.sasl_username:
            config["sasl_plain_username"] = self.sasl_username

        if self.sasl_password:
            config["sasl_plain_password"] = self.sasl_password

        if self.sasl_mechanism:
            config["sasl_mechanism"] = self.sasl_mechanism

        return config

    def _get_or_create(self):
        if self._producer is not None:
            return self._producer

        if KafkaProducer is None:
            logger.error(
                "[KAFKA USER DEVICES] Cliente kafka-python no disponible.",
                extra={
                    "extra_data": {
                        "topic": self.topic,
                        "brokers": self.brokers,
                    }
                },
            )
            return None

        if not self.brokers:
            logger.error(
                "[KAFKA USER DEVICES] No hay brokers configurados; se omite publicacion.",
                extra={"extra_data": {"topic": self.topic}},
            )
            return None

        try:
            self._producer = KafkaProducer(**self._build_client_config())
            return self._producer
        except Exception:
            logger.exception(
                "[KAFKA USER DEVICES] Error inicializando producer.",
                extra={
                    "extra_data": {
                        "topic": self.topic,
                        "brokers": self.brokers,
                        "security_protocol": self.security_protocol,
                    }
                },
            )
            return None

    def publish_update(
        self, payload: dict[str, Any], key: Optional[str] = None
    ) -> bool:
        producer = self._get_or_create()
        if producer is None:
            return False

        try:
            future = producer.send(self.topic, key=key, value=payload)
            future.get(timeout=3)
            producer.flush(timeout=3)
            return True
        except Exception:
            logger.exception(
                "[KAFKA USER DEVICES] Error publicando evento.",
                extra={
                    "extra_data": {
                        "topic": self.topic,
                        "key": key,
                        "type": payload.get("type"),
                        "user_id": payload.get("user_id"),
                        "device_id": payload.get("device_id"),
                    }
                },
            )
            return False

    def close(self) -> None:
        if self._producer is None:
            return

        try:
            self._producer.flush(timeout=3)
            self._producer.close(timeout=3)
        except Exception:
            logger.exception("[KAFKA USER DEVICES] Error cerrando producer.")
        finally:
            self._producer = None

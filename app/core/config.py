import json
from typing import Any, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "SISCOM Admin API"
    API_V1_STR: str = "/api/v1"

    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    # AWS Credentials - Opcionales si usas IAM Role en EC2
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"

    # AWS SNS - Push notifications
    SNS_PLATFORM_APPLICATION_ARN_IOS: Optional[str] = None
    SNS_PLATFORM_APPLICATION_ARN_ANDROID: Optional[str] = None

    # AWS Cognito - Requeridos
    COGNITO_ENDPOINT: Optional[str] = None
    COGNITO_REGION: str
    COGNITO_USER_POOL_ID: str
    COGNITO_CLIENT_ID: str
    COGNITO_CLIENT_SECRET: str
    DEFAULT_USER_PASSWORD: str = "TempPass123!"

    # AWS SES - Email configuration
    SES_FROM_EMAIL: str
    SES_REGION: Optional[str] = None  # Si es None, usa COGNITO_REGION
    SES_ENDPOINT: Optional[str] = None

    # Frontend URL - Para construir las URLs de acción en emails
    FRONTEND_URL: str

    # Contact Email - Email donde se reciben los mensajes de contacto
    CONTACT_EMAIL: Optional[str] = None

    # reCAPTCHA v3 - Secret key para validación
    RECAPTCHA_SECRET_KEY: Optional[str] = None

    # PASETO - Token para compartir ubicación
    PASETO_SECRET_KEY: str

    # KORE Wireless
    KORE_CLIENT_ID: Optional[str] = None
    KORE_CLIENT_SECRET: Optional[str] = None
    KORE_API: Optional[str] = (
        "https://supersim.api.korewireless.com/v1/"  # Base URL de SuperSIM API
    )
    KORE_API_AUTH: Optional[str] = None  # URL del endpoint de autenticación
    KORE_API_SMS: Optional[str] = None  # URL del endpoint de SMS

    # Kafka - Alert rules updates
    KAFKA_BROKERS: str = "localhost:9092"
    KAFKA_RULES_UPDATES_TOPIC: str = "alert-rules-updates"
    KAFKA_GEOFENCES_UPDATES_TOPIC: str = "geofences-updates"
    KAFKA_USER_DEVICES_UPDATES_TOPIC: str = "user-devices-updates"
    KAFKA_RULES_UPDATES_GROUP_ID: str = "alert-rules-updates-group"
    KAFKA_SASL_USERNAME: Optional[str] = "events-alert-consumer"
    KAFKA_SASL_PASSWORD: Optional[str] = "eventsalertconsumerpassword"
    KAFKA_SASL_MECHANISM: str = "SCRAM-SHA-256"
    KAFKA_SECURITY_PROTOCOL: str = "SASL_PLAINTEXT"

    ALLOWED_ORIGINS: list[str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5160",
        "http://127.0.0.1:5160",
        "http://127.0.0.1:8100",
        "http://10.8.0.1:5160",
        "http://10.8.0.1:8100",
        "https://geminislabs.com",
        "https://admin.geminislabs.com",
        "https://nexus.geminislabs.com",
    ]

    LOG_LEVEL: str = "INFO"

    @field_validator(
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "SNS_PLATFORM_APPLICATION_ARN_ANDROID",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("AWS_REGION", mode="before")
    @classmethod
    def normalize_aws_region(cls, v: Optional[str]) -> str:
        if v is None:
            return "us-east-1"
        if isinstance(v, str):
            region = v.strip()
            return region or "us-east-1"
        return str(v)

    @field_validator("COGNITO_REGION")
    @classmethod
    def validate_cognito_region(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError(
                "COGNITO_REGION cannot be empty. "
                "Please set it in your environment variables or .env file. "
                "Example: us-east-1, us-west-2, etc."
            )
        return v.strip()

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v: Any) -> list[str]:
        """Accept JSON array or comma-separated origins from env vars."""
        if v is None:
            return []

        if isinstance(v, list):
            origins = v
        elif isinstance(v, str):
            raw = v.strip()
            if not raw:
                return []

            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = []
                origins = parsed if isinstance(parsed, list) else []
            else:
                origins = [origin.strip() for origin in raw.split(",")]
        else:
            return []

        normalized: list[str] = []
        for origin in origins:
            if not isinstance(origin, str):
                continue
            clean_origin = origin.strip().rstrip("/")
            if clean_origin:
                normalized.append(clean_origin)

        # Preserve order while removing duplicates.
        return list(dict.fromkeys(normalized))

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()

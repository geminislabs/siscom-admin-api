import json
from typing import Annotated, Any, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "SISCOM Admin API"
    API_V1_STR: str = "/api/v1"

    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    # Credencial exclusiva de migraciones. El usuario de runtime (DB_USER) solo
    # tiene DML; alembic necesita DDL. Separarlos evita que la aplicacion pueda
    # alterar el esquema en caliente. Si no se define, alembic cae a DB_USER y
    # se comporta como hasta ahora: no rompe el despliegue por no tenerla.
    DB_MIGRATION_USER: Optional[str] = None
    DB_MIGRATION_PASSWORD: Optional[str] = None

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

    # PASETO - Clave de tokens de SERVICIO interno (GAC/Nexus/App admin).
    # NO usar para tokens de compartir ubicación: firma credenciales
    # administrativas y no debe salir de este servicio.
    PASETO_SECRET_KEY: str

    # Clave dedicada a los tokens de compartir ubicación (v4.local, 32 bytes
    # base64). Se separa de PASETO_SECRET_KEY porque el verificador de estos
    # tokens vive en siscom-api: compartir la clave de servicio le permitiría
    # firmar tokens `internal-*` y llamar a la API interna como administrador.
    # Si no está configurada, /units/{id}/share-location responde 503 en lugar
    # de degradar a la clave de servicio.
    SHARE_LOCATION_KEY_B64: Optional[str] = None

    # ---------------------------------------------------------------------
    # Data token del plano de datos (Fase 1)
    #
    # PASETO v4.public (Ed25519): admin-api FIRMA, siscom-api solo VERIFICA.
    # Asimétrico a propósito — con v4.local el verificador también podría
    # firmar, que es justo la escalada que este diseño elimina.
    # ---------------------------------------------------------------------
    # Clave PRIVADA Ed25519: base64 del PEM PKCS8 en UNA línea. El heredoc que
    # escribe el .env en el despliegue (deploy.yml) rompe con valores multilínea.
    DATA_TOKEN_PRIVATE_KEY_B64: Optional[str] = None
    # Identificador de clave; viaja en el footer del token (que va en claro y
    # autenticado) para poder rotar sin cortar servicio.
    DATA_TOKEN_KEY_ID: str = "v1"
    # Vida máxima del token. Es un techo: si el alcance caduca antes —una ventana
    # horaria de team que cierra— se emite hasta ese límite y no más.
    DATA_TOKEN_MAX_TTL_SECONDS: int = 600
    # Suelo, para no emitir tokens inservibles justo antes de un límite.
    DATA_TOKEN_MIN_TTL_SECONDS: int = 30
    # Audiencia; siscom-api debe rechazar cualquier otra.
    DATA_TOKEN_AUDIENCE: str = "siscom-api"
    # Secreto (base64, 32 bytes) con el que se derivan las claves del índice
    # inverso de revocación. El índice relaciona usuario → scope_refs vivos, así
    # que su clave se deriva por HMAC para que no sea invertible: aunque la ACL
    # de Valkey esté mal desplegada y siscom-api pueda leerla, no aprende de quién
    # es. Sin este secreto no se puede revocar, y sin poder revocar no se emite.
    DATA_TOKEN_INDEX_SECRET_B64: Optional[str] = None

    # Vida de un enlace de compartir ubicación. Más larga que la de un data token
    # de sesión porque el destinatario es una persona que abre un enlace, no un
    # cliente que sabe refrescar.
    SHARE_TOKEN_TTL_SECONDS: int = 1800
    # Interruptor de la migración de compartir ubicación a v4.public. Explícito y
    # no deducido de si hay claves configuradas: el cambio de formato tiene que
    # ocurrir DESPUÉS de que siscom-api sepa verificar el formato nuevo, y esa
    # condición no es observable desde aquí. Ver ADR-005.
    SHARE_LOCATION_USE_DATA_TOKEN: bool = False

    # Valkey (plano de datos). Sin esto no hay dónde materializar el alcance.
    VALKEY_URL: Optional[str] = None
    # Margen del TTL de la clave sobre el del token, para que el alcance nunca
    # expire por debajo de un token todavía válido.
    VALKEY_SCOPE_TTL_MARGIN_SECONDS: int = 300

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
    KAFKA_UNIT_DEVICES_UPDATES_TOPIC: str = "unit-devices-updates"
    KAFKA_USER_UNITS_UPDATES_TOPIC: str = "user-units-updates"
    KAFKA_MOBILITY_TOPIC: str = "mobility-locations-raw"
    KAFKA_TEAM_RULES_TOPIC: str = "team-rules-updates"
    KAFKA_RULES_UPDATES_GROUP_ID: str = "alert-rules-updates-group"
    KAFKA_SASL_USERNAME: Optional[str] = "events-alert-consumer"
    KAFKA_SASL_PASSWORD: Optional[str] = "eventsalertconsumerpassword"
    KAFKA_SASL_MECHANISM: str = "SCRAM-SHA-256"
    KAFKA_SECURITY_PROTOCOL: str = "SASL_PLAINTEXT"

    # NoDecode evita que EnvSettingsSource intente json.loads sobre el valor
    # crudo: sin él, un CSV revienta en la fuente antes de llegar al validador.
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5160",
        "http://127.0.0.1:5160",
        "http://127.0.0.1:8100",
        "http://10.8.0.1:5160",
        "http://10.8.0.1:8100",
        "https://geminislabs.com",
        "https://www.geminislabs.com",
        "https://admin.geminislabs.com",
        "https://nexus.geminislabs.com",
    ]

    LOG_LEVEL: str = "INFO"

    # Observabilidad (OTLP). Vacío = telemetría silenciosa (no-op).
    # Se lee en runtime; no hornear en la imagen.
    OTLP_ENDPOINT: str = ""
    DEPLOY_ENV: str = "local"
    SERVICE_NAME: str = "siscom-admin-api"
    # Centinela a proposito: la version del build vive hoy solo en el tag de git
    # y nada la inyecta todavia. Un "0.1.0" por defecto se lee como un dato
    # legitimo y miente; "unknown" declara que no se sabe. Se rellena cuando el
    # commit de release la escriba en el repo (ver docs/RELEASE.md).
    SERVICE_VERSION: str = "unknown"

    # Stripe — None cuando no está configurado (initialize_gateways lo omite)
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None

    # Facturapi — CFDI 4.0. None desactiva el timbrado (el comprobante interno sigue).
    FACTURAPI_API_KEY: Optional[str] = None
    FACTURAPI_PRODUCT_KEY: str = "81112100"
    FACTURAPI_UNIT_KEY: str = "E48"

    # Usuario técnico Siscom para registered_by en pagos manuales desde GAC
    GAC_SYSTEM_USER_ID: Optional[str] = None

    @field_validator(
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "SNS_PLATFORM_APPLICATION_ARN_IOS",
        "SNS_PLATFORM_APPLICATION_ARN_ANDROID",
        "FACTURAPI_API_KEY",
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

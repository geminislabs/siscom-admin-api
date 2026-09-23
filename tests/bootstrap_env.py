"""Apply test-only environment defaults before app Settings() loads."""

import os

# Los tests corren contra un PostgreSQL real, no contra SQLite: el esquema de
# este sistema es especifico de Postgres (JSONB, ARRAY, UUID, server_defaults,
# locks consultivos) y un motor sustituto solo puede probarlo falseandolo.
# Ver §20 del documento de arquitectura.
#
# Los valores por defecto apuntan al harness local (docker-compose.db.yml).
# En CI los pisa el servicio de Postgres del workflow.
_TEST_ENV_DEFAULTS = {
    "DB_HOST": os.getenv("TEST_DB_HOST", "localhost"),
    "DB_PORT": os.getenv("TEST_DB_PORT", "55432"),
    "DB_USER": os.getenv("TEST_DB_USER", "postgres"),
    "DB_PASSWORD": os.getenv("TEST_DB_PASSWORD", "postgres"),
    "DB_NAME": os.getenv("TEST_DB_NAME", "siscom_test"),
    "COGNITO_REGION": "us-east-1",
    "COGNITO_USER_POOL_ID": "us-east-1_testpool",
    "COGNITO_CLIENT_ID": "test-client-id",
    "COGNITO_CLIENT_SECRET": "test-client-secret",
    "SES_FROM_EMAIL": "test@example.com",
    "FRONTEND_URL": "http://localhost:3000",
    "PASETO_SECRET_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    # Distinta de PASETO_SECRET_KEY a propósito: los tests deben correr
    # con las dos claves separadas, igual que producción.
    # gitleaks:allow — valor fijo de test, no es un secreto real. Se anota en
    # línea en vez de meter tests/ en el allowlist de .gitleaks.toml: eso haría
    # que un secreto de verdad pegado en un test pasara desapercibido.
    "SHARE_LOCATION_KEY_B64": "c2hhcmUtbG9jYXRpb24tdGVzdC1rZXktMzJieXRlcyE=",  # gitleaks:allow
    "STRIPE_SECRET_KEY": "sk_test_siscom_unit_tests",
    "STRIPE_PUBLISHABLE_KEY": "pk_test_siscom_unit_tests",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_siscom_unit_tests",
    "FACTURAPI_API_KEY": "sk_test_siscom_unit_tests",
    "OTLP_ENDPOINT": "",
    "DEPLOY_ENV": "test",
    "SERVICE_NAME": "siscom-admin-api",
    "SERVICE_VERSION": "0.1.0",
}


def apply_test_env_defaults() -> None:
    for key, value in _TEST_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)
    # Los tests no exportan al Collector aunque el .env local tenga URL.
    os.environ["OTLP_ENDPOINT"] = ""


def bootstrap_test_runtime() -> None:
    apply_test_env_defaults()

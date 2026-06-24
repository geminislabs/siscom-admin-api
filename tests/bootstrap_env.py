"""Apply test-only environment defaults before app Settings() loads."""

import os

from tests.sqlite_dialect import register_sqlite_dialect_compat

_TEST_ENV_DEFAULTS = {
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_USER": "test",
    "DB_PASSWORD": "test",
    "DB_NAME": "test",
    "COGNITO_REGION": "us-east-1",
    "COGNITO_USER_POOL_ID": "us-east-1_testpool",
    "COGNITO_CLIENT_ID": "test-client-id",
    "COGNITO_CLIENT_SECRET": "test-client-secret",
    "SES_FROM_EMAIL": "test@example.com",
    "FRONTEND_URL": "http://localhost:3000",
    "PASETO_SECRET_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
}


def apply_test_env_defaults() -> None:
    for key, value in _TEST_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)


def bootstrap_test_runtime() -> None:
    apply_test_env_defaults()
    register_sqlite_dialect_compat()

# AGENTS.md — Guía para agentes de código

Instrucciones para asistentes de IA (Cursor, Copilot, etc.) que trabajen en este repositorio.

## Proyecto

**siscom-admin-api** — API FastAPI de administración Geminis Labs: cuentas, organizaciones, usuarios (Cognito), unidades, geocercas, billing, API platform e integraciones internas (PASETO/GAC).

## Stack

| Capa        | Tecnología                          |
| ----------- | ----------------------------------- |
| Framework   | FastAPI + Uvicorn                   |
| ORM         | SQLAlchemy 2 / SQLModel             |
| DB          | PostgreSQL + Alembic                |
| Auth        | AWS Cognito (JWT) + PASETO interno  |
| Lint/format | Ruff + Black                        |
| Tests       | pytest + pytest-cov                 |
| Runtime     | Python 3.12+                        |
| Deploy      | Docker → EC2 (tags `v*.*.*`)      |

## Estructura

```text
app/api/v1/endpoints/   # REST público e internal/
app/services/           # lógica de negocio
app/models/             # SQLModel
app/schemas/            # Pydantic DTOs
app/db/migrations/      # Alembic
tests/                  # pytest (SQLite in-memory en conftest)
docs/                   # guías y API docs
```

## Convenciones

- **Python 3.12+** (ver `.python-version`).
- **Formato:** Black (88 cols), Ruff para lint.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `chore:`, etc.).
- **Alcance:** Cambios mínimos y enfocados. No reformatear código no relacionado.

## Comandos obligatorios antes de terminar

```bash
make validate
```

Equivalente: `make lint`, `make format-check`, `make test`, `docker build`.

Opcional: `make scan-secrets`, `make audit-deps`, `pre-commit run --all-files`.

## Módulos sensibles

- `app/core/security.py`, `app/api/deps.py` — auth Cognito y RBAC
- `app/api/v1/endpoints/internal/` — API PASETO para GAC
- `app/services/gateways/stripe_gateway.py` — pagos
- `app/services/messaging/kafka_producer.py` — eventos Kafka

## Deploy

- CI en PR/push a `develop`/`master` (`.github/workflows/ci.yml`)
- Deploy automático al pushear tag `v*.*.*` (`.github/workflows/deploy.yml`)

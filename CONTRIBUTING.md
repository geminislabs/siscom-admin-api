# Guía de contribución

Gracias por contribuir a **siscom-admin-api**.

## Requisitos previos

- **Python 3.12+** (ver `.python-version`)
- PostgreSQL para desarrollo local (o Docker según `docker-compose.yml`)

```bash
bash scripts/setup.sh
cp .env.example .env   # ajustar variables
```

> Opcional: abre el repo en el **DevContainer** (`.devcontainer/`) para un entorno Python 3.12 listo (ejecuta `scripts/setup.sh` automáticamente). Postgres y Kafka son servicios externos; apunta tu `.env` a ellos.

## Flujo de trabajo

### 1. Rama base

Trabaja desde `develop`:

```bash
git checkout develop
git pull origin develop
git checkout -b <tipo>/<descripcion-corta>
```

| Prefijo     | Uso                                         |
| ----------- | ------------------------------------------- |
| `feature/`  | Nueva funcionalidad                         |
| `fix/`      | Corrección de bug                           |
| `chore/`    | Tooling, docs, dependencias, CI             |
| `refactor/` | Cambio interno sin cambio de comportamiento |
| `test/`     | Solo tests                                  |

### 2. Commits

[Conventional Commits](https://www.conventionalcommits.org/):

```text
<tipo>(<alcance opcional>): <descripción en imperativo>
```

### 3. Antes de abrir un PR

```bash
make validate
```

Equivalente manual:

```bash
make lint
make format-check
make test
docker build -t siscom-admin-api:local .
```

Opcional:

```bash
make scan-secrets
make audit-deps
make scan-osv
make test-cov    # incluye umbral de cobertura (ver docs/GOVERNANCE.md)
pre-commit run --all-files
```

### 4. Pull requests

- Base branch: **`develop`**
- Usa la plantilla de PR (`.github/pull_request_template.md`)
- Actualiza `CHANGELOG.md` en `[Unreleased]` si el cambio es visible

## Hooks locales

```bash
pre-commit install
```

Incluye Ruff, Black y checks de hygiene. Gitleaks: `make scan-secrets`.

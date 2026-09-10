# Threat Model — siscom-admin-api

Modelo de seguridad de alto nivel para la API administrativa (FastAPI). Complementa [SECURITY.md](../../SECURITY.md).

## System boundary

| In scope (este repo)                        | Out of scope (otros sistemas)              |
| ------------------------------------------- | ------------------------------------------ |
| Endpoints REST `/api/v1` (FastAPI)          | AWS Cognito (user pool, infraestructura)   |
| Auth JWT (Cognito) y PASETO interno (GAC)   | PostgreSQL gestionado / red de la VPC      |
| Lógica de negocio en `app/services/`        | Broker Kafka y consumidores downstream     |
| Migraciones Alembic                         | Stripe (procesamiento de pagos)            |
| Imagen Docker y deploy por tags             | Firmware de dispositivos                   |

## Assets

1. **Tokens de sesión** — JWT de Cognito validados en cada request
2. **Tokens PASETO internos** — autenticación servicio-a-servicio con GAC
3. **Datos de cuentas/organizaciones/usuarios** — PII y relaciones comerciales
4. **Secretos** — credenciales DB, Cognito, Stripe, SES, KORE, Kafka (vía env, nunca en repo)
5. **Eventos Kafka** — cambios administrativos publicados a otros servicios

## Trust zones

```text
[Cliente web / móvil]  --HTTPS+JWT-->  [siscom-admin-api]  --TCP-->  [PostgreSQL]
[GAC u otros servicios] --HTTPS+PASETO--^         |
                                                  └--SASL-->  [Kafka]
```

**Regla:** los secretos viven en variables de entorno (ver `.env.example`); nunca en el código ni en git.

## Key flows

### Autenticación y autorización

- JWT de Cognito validado en `app/core/security.py` y `app/api/deps.py`
- RBAC por roles de cuenta/organización en dependencias de FastAPI
- API interna (PASETO) en `app/api/v1/endpoints/internal/` para GAC
- **Riesgo:** token robado/replay → mitigar con expiración corta, HTTPS, validación de firma
- **Riesgo:** escalamiento de privilegios → cada endpoint valida rol/propiedad del recurso

#### Identidad por marca (migración `028`, Fase 3)

`users.email` dejó de ser único global: lo es por marca
(`UNIQUE (brand_account_id, email)`, con un índice parcial para la marca por
defecto). Ver [Identidad y marca](../architecture/identidad-y-marca.md).

- **Riesgo:** que una búsqueda de credencial por correo **sin marca** devuelva la
  fila de otra marca → toda consulta de login/recuperación filtra por
  `brand_account_id`; la base impone la unicidad, pero no elige por ti cuál de
  dos filas es la correcta
- **Riesgo:** tratar el `Host` como autorización → el `Host` resuelve marca
  (apariencia y contra qué credencial se busca) y **nunca** concede acceso a
  datos; el aislamiento sigue siendo `account_path` / `organization_id`
- **Riesgo:** que Cognito se vuelva fuente de verdad → sus atributos custom son
  mutables desde las APIs de administración; el claim de cuenta o de marca se
  revalida siempre contra Postgres
- **Riesgo:** enumeración de correos en la recuperación de contraseña → el mismo
  correo puede existir en dos marcas y **son personas distintas**; la respuesta
  genérica de `forgot-password` sigue siendo obligatoria, y el código de reseteo
  se emite para la credencial de *esa* marca, no para el correo
- **Riesgo:** un secreto en `accounts.idp_config` → esa columna lleva
  configuración y referencias a Secrets Manager, nunca credenciales: acabaría en
  respaldos, dumps de soporte y logs de consulta lenta

### Pagos (Stripe)

- `app/services/gateways/` y `stripe_billing.py` manejan webhooks y cobros
- **Riesgo:** webhook falsificado → validar firma de Stripe; nunca confiar en payload sin verificar
- **Riesgo:** fuga de claves → claves Stripe solo por env

### Mensajería (Kafka)

- `app/services/messaging/kafka_producer.py` publica eventos administrativos
- **Riesgo:** mensajes no autorizados → SASL/credenciales por env; el productor no expone endpoints públicos

## STRIDE summary (backend-focused)

| Threat                 | Ejemplo                          | Mitigación                                          |
| ---------------------- | -------------------------------- | --------------------------------------------------- |
| Spoofing               | Token o webhook falso            | Validación JWT/PASETO, firma de Stripe              |
| Tampering              | Modificar payloads de request    | Validación Pydantic, autorización por recurso       |
| Repudiation            | Negar una acción                 | Logs estructurados (`app/core/logging_config.py`)   |
| Information disclosure | Secretos en git / en respuestas  | Gitleaks, `.env` gitignored, no exponer `token_hash`|
| Denial of service      | Flood de requests                | Rate limiting / WAF a nivel infraestructura         |
| Elevation of privilege | Acceder a recursos de otra cuenta| RBAC + validación de pertenencia en cada endpoint   |

## Sensitive modules (revisión extra)

- `app/core/security.py`, `app/api/deps.py` — auth y RBAC
- `app/api/v1/endpoints/auth.py` — login, altas en Cognito e identidad por marca
- `app/api/v1/endpoints/internal/` — API PASETO para GAC
- `app/utils/paseto_token.py` — emisión/validación de tokens internos
- `app/services/gateways/` y `app/api/v1/endpoints/stripe_billing.py` — pagos
- `app/services/messaging/kafka_producer.py` — eventos Kafka

## Reporting

Sigue [SECURITY.md](../../SECURITY.md) para divulgación de vulnerabilidades. No abras issues públicos para bugs de seguridad.

## Riesgos aceptados

Vulnerabilidades conocidas que **no se van a corregir**, con el porqué. Existe
esta sección porque la decisión estaba repartida entre la configuración de dos
escáneres y no en ningún sitio legible: quien viera la alerta por tercera vez
volvía a investigarla desde cero.

### `ecdsa` — Minerva, ataque de timing sobre P-256

- **Identificadores**: `GHSA-wj6h-64fc-37mp`, `CVE-2024-23342`, `PYSEC-2026-1325`.
- **Severidad declarada**: alta. **Sin versión corregida**: los mantenedores de
  `python-ecdsa` consideran los ataques de canal lateral fuera de alcance.
- **Cómo llega**: transitiva vía `python-jose`, que es la librería de JWT.
- **Por qué no aplica aquí**: Minerva ataca el *firmado* ECDSA sobre P-256.
  `app/core/security.py` hace una sola llamada a la librería —`jwt.decode(...,
  algorithms=["RS256"])`— y RS256 es RSA, no curva elíptica. No se firma nada,
  no se generan claves y no hay ECDH. El camino vulnerable no se ejecuta.
- **Dónde está registrada la excepción**, que ahora son tres sitios y deben
  seguir coincidiendo:
  - `osv-scanner.toml` → `[[IgnoredVulns]] id = "GHSA-wj6h-64fc-37mp"`
  - `scripts/pip-audit-scan.sh` → `--ignore-vuln PYSEC-2026-1325`
  - La alerta de Dependabot (#18), descartada el 8/09/2026 con motivo `not_used`
- **Qué la cerraría de verdad**: quitar `python-jose`. Se usa para exactamente
  una llamada, y `PyJWT` + `cryptography` hace la misma verificación RS256 sin
  arrastrar `ecdsa`. Es un cambio en el camino de verificación de tokens, así
  que merece su propio PR y sus pruebas, no ir de pasada.

**Al revisar esta lista**: una excepción deja de ser válida en cuanto cambia el
uso. Si algún día se firma con ECDSA o se acepta ES256 en `jwt.decode`, esta
entrada se invalida y hay que quitar la dependencia.

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
- `app/api/v1/endpoints/internal/` — API PASETO para GAC
- `app/utils/paseto_token.py` — emisión/validación de tokens internos
- `app/services/gateways/` y `app/api/v1/endpoints/stripe_billing.py` — pagos
- `app/services/messaging/kafka_producer.py` — eventos Kafka

## Reporting

Sigue [SECURITY.md](../../SECURITY.md) para divulgación de vulnerabilidades. No abras issues públicos para bugs de seguridad.

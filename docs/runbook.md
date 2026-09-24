# Runbook — observabilidad siscom-admin-api

## OTLP_ENDPOINT vacío

No es un error. La API arranca igual y no exporta traces, logs ni métricas.
`GET /health` sigue respondiendo.

**Cómo se enciende**, que no requiere tocar código ni reconstruir la imagen:
se define la variable **`OTLP_ENDPOINT`** en el entorno **`test`** de
`geminislabs/siscom-admin-api` —donde viven `ALLOWED_ORIGINS`, `FRONTEND_URL` y
las demás— con la URL del Collector, y se redespliega. El workflow la escribe en
el `.env` que él mismo genera en la EC2.

Para el sitio es la misma variable, en el entorno `test` de
`geminislabs/geminis-labs-web-page`. Ahí además viaja al build, porque el bundle
del navegador la hornea: sin ella, la telemetría de browser queda apagada aunque
la del servidor esté encendida.

Vacía o sin definir = silencio. Es el valor por defecto a propósito.

## Verificar que los spans llegan

1. `curl -sS http://localhost:8100/health` — debe incluir `environment` y `version`.
2. Un `POST /api/v1/auth/login` (u otro endpoint) con header `traceparent` del frontend.
3. En Jaeger: servicio `siscom-admin-api`. El waterfall debe mostrar el span
   HTTP y un child de SQLAlchemy.

Si el Collector no está arriba, el export falla en background; el proceso no
se cae.

## Correlacionar logs y traces

Cada línea JSON en stdout incluye `trace_id` y `span_id` cuando hay un span
activo. Copiar `trace_id` y buscarlo en Jaeger.

## Rollback

Revertir este branch solo quita dependencias OTel, `app/observability/` y
los hooks de init. No cambia contratos de negocio ni el esquema. Con
`OTLP_ENDPOINT` vacío el rollback funcional es equivalente a no haber
instrumentado.

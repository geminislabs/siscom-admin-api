# Runbook — observabilidad siscom-admin-api

## OTLP_ENDPOINT vacío

No es un error. La API arranca igual y no exporta traces, logs ni métricas.
`GET /health` sigue respondiendo. Para ver datos en Jaeger hay que setear
`OTLP_ENDPOINT` en runtime (no reconstruir la imagen) a la URL del Collector
del entorno.

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

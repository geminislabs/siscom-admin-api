# SLOs — siscom-admin-api

Contrato de servicio. Las señales las produce esta API; el routing
(Slack/PagerDuty) y el Grafana viven fuera de este repositorio.

| SLI | Objetivo | Señal |
|-----|----------|--------|
| Disponibilidad HTTP | 99.5% no-5xx | `http_server_duration_count` (excl. `/health`) |
| Latencia p95 endpoints | < 500 ms | histograma `http_server_duration` |
| Auth success rate | > 95% | `auth_attempts_total{outcome="success"}` |
| API error rate | < 1%/min | `api_errors_total` por endpoint |

Ventana de evaluación recomendada: 30 días para disponibilidad; 1 hora para
auth y error rate operativos.

Con `OTLP_ENDPOINT` vacío no hay series: no es un incumplimiento del SLO, es
telemetría silenciosa.

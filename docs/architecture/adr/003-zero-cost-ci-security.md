# ADR-003: Tooling de seguridad en CI sin costo

**Estado:** Aceptado
**Fecha:** 2026-06-24
**Autores:** Equipo de Desarrollo
**Revisores:** -

## Contexto

`geminislabs` es una organización de GitHub. Algunas integraciones de seguridad (por ejemplo la action oficial de Gitleaks para repos de organización, o GitHub Advanced Security) requieren licencia de pago. Necesitábamos escaneo de secretos, análisis estático y auditoría de dependencias sin costo adicional y reproducible en local.

### Problema a resolver

- Detectar secretos filtrados y vulnerabilidades de dependencias en cada PR.
- Hacerlo sin licencias de pago y con paridad local/CI.

## Decisión

Usar **herramientas open-source auto-ejecutadas** en el job `security` de CI:

- **Gitleaks CLI** vía `scripts/gitleaks-scan.sh` (sin `GITLEAKS_LICENSE`), con `.gitleaks.toml` y `.gitleaks-baseline.json` para hallazgos históricos.
- **Semgrep OSS** con reglas comunitarias (`p/python`, `p/secrets`).
- **pip-audit** vía `scripts/pip-audit-scan.sh` sobre `requirements.txt`.
- **OSV-Scanner** vía `scripts/osv-scan.sh`, con `osv-scanner.toml` para ignores documentados.

Las alternativas de pago (GitHub Advanced Security, Semgrep App) quedan fuera de alcance salvo que se apruebe presupuesto.

## Consecuencias

### Positivas

- Costo $0; los mismos escáneres corren en local y en CI (`make scan-secrets`, `make audit-deps`, `make scan-osv`).
- Cobertura complementaria: pip-audit y OSV usan bases de datos distintas.

### Negativas

- Mantenemos scripts de instalación y allowlists nosotros mismos.

### Neutrales

- La estrictez del enforcement es escalonada (soft primero, gates duros después).

## Alternativas consideradas

### GitHub Advanced Security / CodeQL Advanced

**Descartado** porque: requiere licencia de pago para repos privados de organización.

### Solo pip-audit

**Descartado** porque: OSV-Scanner aporta cobertura adicional de advisories que pip-audit no marca.

## Referencias

- `docs/GOVERNANCE.md`
- `scripts/gitleaks-scan.sh`, `scripts/pip-audit-scan.sh`, `scripts/osv-scan.sh`
- `osv-scanner.toml`, `.gitleaks.toml`

## Registro de cambios

| Fecha | Versión | Cambios |
|-------|---------|---------|
| 2026-06-24 | 1.0 | Documento inicial |

# ADR-002: Línea base de gobernanza de ingeniería

**Estado:** Aceptado
**Fecha:** 2026-06-24
**Autores:** Equipo de Desarrollo
**Revisores:** -

## Contexto

`siscom-admin-api` necesitaba una línea base de ingeniería consistente con el resto del ecosistema Geminis Labs (frontends y demás APIs), sin frenar al equipo ni introducir herramientas de pago. Antes de este esfuerzo, el repositorio carecía de CI bloqueante, hooks estandarizados, documentación de contribución y compuertas de calidad.

### Problema a resolver

- Falta de CI que validara formato, lint, tests y build de forma consistente.
- Ausencia de disciplina de release y de documentación para contribuir.
- Sin compuertas de calidad (cobertura, escaneo de dependencias) ni reglas de revisión.

## Decisión

Adoptar la línea base en tres incrementos, un PR por incremento:

1. **Engineering foundation** (`chore/engineering-foundation`): `ci.yml` con jobs `quality` y `security` bloqueantes, `deploy.yml` separado por tags, hooks pre-commit (Ruff, Black), docs (`AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/RELEASE.md`), `.editorconfig`, `.python-version` y `make validate`.
2. **Soft foundations** (`chore/soft-foundations`): DevContainer, threat model, plantillas de issues y ADRs de proceso. No endurece el pipeline.
3. **Quality gates** (`chore/quality-gates`): `CODEOWNERS`, Dependabot, `docs/GOVERNANCE.md`, piso de cobertura (65% sobre `app/`) y OSV-Scanner.

El enforcement duro se introduce solo en la fase de quality gates, una vez estable la base.

## Consecuencias

### Positivas

- Pipeline reproducible localmente (`make validate`) y en CI.
- Onboarding más rápido (DevContainer, docs, plantillas).
- Calidad protegida contra regresiones sin bloquear el desarrollo diario.

### Negativas

- Mantenimiento de scripts y configuraciones propias (hooks, escáneres).

### Neutrales

- El playbook es reconocible en todos los repos de Geminis Labs.

## Alternativas consideradas

### Un solo PR monolítico de gobernanza

**Descartado** porque: dificulta la revisión y mezcla cambios de naturaleza distinta (infra vs. enforcement vs. DX).

### Herramientas de seguridad de pago (GitHub Advanced Security)

**Descartado** porque: existe alternativa OSS sin costo (ver ADR-003).

## Referencias

- `docs/GOVERNANCE.md`
- `CONTRIBUTING.md`, `AGENTS.md`

## Registro de cambios

| Fecha | Versión | Cambios |
|-------|---------|---------|
| 2026-06-24 | 1.0 | Documento inicial |

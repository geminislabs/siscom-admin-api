# Architecture Decision Records (ADR)

Este directorio contiene los **Architecture Decision Records (ADR)** del proyecto siscom-admin-api.

## ¿Qué es un ADR?

Un ADR es un documento que captura una decisión arquitectónica importante junto con su contexto y consecuencias. Sirve como registro histórico de por qué se tomaron ciertas decisiones.

## Formato

Cada ADR sigue esta estructura:

1. **Título**: Nombre descriptivo de la decisión
2. **Estado**: Propuesto | Aceptado | Deprecado | Reemplazado
3. **Contexto**: El problema o situación que requiere una decisión
4. **Decisión**: La decisión tomada y su justificación
5. **Consecuencias**: Impacto positivo, negativo y neutral
6. **Alternativas**: Opciones consideradas y por qué se descartaron

## Índice de ADRs

| ID | Título | Estado | Fecha |
|----|--------|--------|-------|
| [ADR-001](./001-account-organization-user-model.md) | Migración al Modelo Account / Organization / User | Aceptado | 2024-12-29 |
| [ADR-002](./002-engineering-governance-baseline.md) | Línea base de gobernanza de ingeniería | Aceptado | 2026-06-24 |
| [ADR-003](./003-zero-cost-ci-security.md) | Tooling de seguridad en CI sin costo | Aceptado | 2026-06-24 |

## Crear un nuevo ADR

1. Copia la plantilla de abajo
2. Nombra el archivo con el siguiente número secuencial: `NNN-titulo-descriptivo.md`
3. Completa todas las secciones
4. Agrega la entrada al índice de este README
5. Solicita revisión del equipo

## Plantilla

```markdown
# ADR-NNN: [Título descriptivo]

**Estado:** Propuesto
**Fecha:** YYYY-MM-DD
**Autores:** [Nombres]
**Revisores:** [Nombres]

## Contexto

[Describe el problema o situación que requiere una decisión]

## Decisión

[Describe la decisión tomada y su justificación]

## Consecuencias

### Positivas
- [Beneficio 1]
- [Beneficio 2]

### Negativas
- [Desventaja 1]
- [Desventaja 2]

### Neutrales
- [Impacto neutral 1]

## Alternativas consideradas

### [Alternativa 1]
**Descartado** porque: [razón]

### [Alternativa 2]
**Descartado** porque: [razón]

## Referencias

- [Link a documentación relevante]

## Registro de cambios

| Fecha | Versión | Cambios |
|-------|---------|---------|
| YYYY-MM-DD | 1.0 | Documento inicial |
```

## Convenciones

- **Numeración**: Usar números de 3 dígitos (001, 002, etc.)
- **Nombres de archivo**: Usar kebab-case en minúsculas
- **Estado**: Actualizar cuando cambie el estado de la decisión
- **Inmutabilidad**: No modificar ADRs aceptados; crear uno nuevo que lo reemplace si es necesario

# Política de versiones de las apps móviles

Qué versión de NEXUS para iOS y Android se acepta la decide el servidor, en
`public.client_version_policy` (migración 047). La consulta la app al arrancar
con `GET /api/v1/client-config`, y el middleware 426 la hace cumplir en cada
petición que trae `X-Client-Platform` y `X-Client-Version`.

**La vía normal es GAC**: Productos → Nexus → Versiones de app
(`/products/nexus/app-versions`). Antes de guardar muestra cuántas instalaciones
activas quedarían bloqueadas o avisadas (`preview`), pide confirmación explícita
si se bloquea a alguien, valida lo mismo que el servidor y firma el cambio con
el usuario de GAC (`updated_by = gac:<uuid>`). Contrato en
[`docs/api/client-version-policy.md`](../api/client-version-policy.md).

El SQL de abajo queda **sólo de respaldo** (GAC caído, emergencia). Por SQL no
hay validación: una versión mal escrita se ignora en silencio y un mínimo sin
`store_url` deja al usuario en una pantalla sin salida. **Siempre con
`updated_by`**: es la única auditoría que tiene.

## Las columnas

| Columna | Efecto |
|---|---|
| `min_supported_version` | Por debajo: `update = required`. La app se bloquea y manda a la tienda. `NULL` = sin mínimo |
| `latest_version` | Por debajo: `update = optional`. Aviso que se puede cerrar. `NULL` = sin aviso |
| `blocked_versions` | Versiones concretas rotas: `required` aunque superen el mínimo |
| `store_url` | La ficha de la tienda a la que manda la app |

La comparación es numérica por segmentos (`1.10.0 > 1.9.0`). Una versión que no
se puede leer da `none`: nunca se bloquea por un error de parseo. Un umbral mal
escrito en la tabla se ignora y deja un `client_version_policy.umbral_ilegible`
en el log.

## Anunciar una versión nueva (aviso opcional)

```sql
UPDATE public.client_version_policy
   SET latest_version = '1.2.0',
       store_url      = 'https://apps.apple.com/app/id<ID>',
       updated_at     = now(),
       updated_by     = '<tu correo>'
 WHERE platform = 'ios';
```

## Obligar a actualizar

**Antes**, comprobar en `mobility.devices` cuántos usuarios activos quedarían
fuera:

```sql
SELECT app_version, count(*) AS instalaciones
  FROM mobility.devices
 WHERE platform = 'ios' AND last_seen_at > now() - interval '30 days'
 GROUP BY app_version ORDER BY instalaciones DESC;
```

```sql
UPDATE public.client_version_policy
   SET min_supported_version = '1.2.0',
       updated_at = now(),
       updated_by = '<tu correo>'
 WHERE platform = 'ios';
```

## Bloquear una versión rota

```sql
UPDATE public.client_version_policy
   SET blocked_versions = array_append(blocked_versions, '1.2.1'),
       updated_at = now(),
       updated_by = '<tu correo>'
 WHERE platform = 'android';
```

## Comprobar el efecto

```bash
curl -s 'https://admin.geminislabs.com/api/v1/client-config?platform=ios&version=1.1.0'
```

## Deshacer

Volver a `NULL` (o quitar la versión de `blocked_versions`). El efecto es
inmediato en `client-config`; el middleware 426 tardará lo que dure su caché.

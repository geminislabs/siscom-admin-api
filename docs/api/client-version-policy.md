# API de política de versiones (apps móviles)

## Descripción

Qué versiones de NEXUS para iOS y Android se aceptan. Vive en
`public.client_version_policy` (migración 047), una fila por plataforma.

- `GET /api/v1/client-config` la consulta la app al arrancar (público, sin auth).
- El middleware 426 la hace cumplir en cada petición que trae `X-Client-Platform`
  y `X-Client-Version`.
- Las rutas de abajo la administran desde **GAC** (pantalla
  `/products/nexus/app-versions` de gac-web). Sustituyen al SQL del runbook
  [`politica-de-versiones.md`](../runbooks/politica-de-versiones.md).

Un cambio se aplica en `client-config` al instante y en el middleware en
**hasta 60 segundos** (caché por worker; la del worker que guarda se vacía al
guardar).

| Campo | Efecto en la app |
|---|---|
| `min_supported_version` | Por debajo: actualización **obligatoria**. `null` = sin mínimo |
| `latest_version` | Por debajo: aviso **opcional**. `null` = sin aviso |
| `blocked_versions` | Versiones concretas rotas: **obligatoria** aunque superen el mínimo |
| `store_url` | Ficha de la tienda a la que manda la app |

La comparación es numérica por segmentos (`1.10.0 > 1.9.0`, `1.2 == 1.2.0`).

## Autenticación

Sólo el PASETO interno de GAC (`service = gac`, `role = GAC_ADMIN`):

```text
Authorization: Bearer <paseto de gac-api>
```

Sin token: 401. Otro rol de servicio o un token de Cognito: 401/403.

## Errores 422

Siempre con esta forma, también los de validación del cuerpo o de `days`:

```json
{ "detail": "store_url debe ser https://apps.apple.com/…", "field": "store_url" }
```

`field` es `null` si el error no es de un campo concreto (p. ej. cuerpo que no es JSON).

---

## `GET /api/v1/client-version-policy`

Las dos filas, ordenadas por plataforma.

```json
[
  {
    "platform": "android",
    "min_supported_version": null,
    "latest_version": "1.2.0",
    "blocked_versions": ["1.1.3"],
    "store_url": "https://play.google.com/store/apps/details?id=com.geminislabs.nexus",
    "updated_at": "2026-11-07T02:16:30Z",
    "updated_by": "gac:5b1f…"
  },
  { "platform": "ios", "…": "…" }
]
```

`updated_by` es `gac:<internal_id del usuario de GAC>`, `gac` si el token no trae
`internal_id`, un texto libre (cambios por SQL) o `null`.

## `PUT /api/v1/client-version-policy/{platform}`

Reemplaza la fila entera. Los cuatro campos son obligatorios (`null` vale; un
texto vacío se guarda como `null`). Campos desconocidos: 422.

```json
{
  "min_supported_version": "1.2.0",
  "latest_version": "1.3.0",
  "blocked_versions": ["1.2.1"],
  "store_url": "https://apps.apple.com/mx/app/nexus-geminislabs/id6760983231"
}
```

- **200**: la fila guardada (misma forma que el `GET`).
- **404**: `platform` no es `ios` ni `android`.
- **422** si:
  - una versión no se puede leer (`1`, `1.2`, `1.2.3`, con `v` inicial opcional);
  - `min_supported_version > latest_version`;
  - `blocked_versions` tiene repetidas (`1.2` y `1.2.0` cuentan como la misma)
    o más de 50;
  - `store_url` no es `https://` con host `apps.apple.com` (ios) o
    `play.google.com` (android);
  - hay mínimo **o** versiones bloqueadas sin `store_url`: obligar a actualizar
    sin decir adónde ir deja al usuario sin salida.

Deja en el log `client_version_policy.actualizada` con `antes`, `despues` y
`updated_by`.

## `GET /api/v1/client-version-policy/{platform}/installs?days=30`

Instalaciones vistas en los últimos `days` días (1–365, por defecto 30), por
versión. Cuenta filas de `mobility.devices` por `last_seen_at` (no por
`is_active`: cerrar sesión apaga el push, no desinstala). Sin versión →
`desconocida`. Sólo conteos.

```json
{
  "platform": "ios",
  "days": 30,
  "total": 412,
  "versions": [
    { "app_version": "1.1.0", "installs": 300 },
    { "app_version": "1.0.1", "installs": 100 },
    { "app_version": "desconocida", "installs": 12 }
  ]
}
```

## `POST /api/v1/client-version-policy/{platform}/preview?days=30`

El mismo cuerpo y los mismos 422 que el `PUT`. **No guarda nada.** Clasifica
cada versión instalada con la misma regla que `client-config`; una versión
ilegible o `desconocida` sale `none`.

```json
{
  "platform": "ios",
  "days": 30,
  "total": 412,
  "required": 100,
  "optional": 300,
  "versions": [
    { "app_version": "1.1.0", "installs": 300, "update": "optional" },
    { "app_version": "1.0.1", "installs": 100, "update": "required" },
    { "app_version": "desconocida", "installs": 12, "update": "none" }
  ]
}
```

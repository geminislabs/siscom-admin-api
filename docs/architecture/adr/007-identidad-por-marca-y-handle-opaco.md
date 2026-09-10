# ADR-007: La credencial pertenece a una marca, y el handle del proveedor es opaco

**Estado:** Aceptado
**Fecha:** 2026-09-08
**Autores:** Equipo de Desarrollo
**Revisores:** -

## Contexto

La Fase 3 (§5, §11 del documento de arquitectura) abstrae la identidad para que
la misma persona pueda existir bajo dos marcas distintas, y para que mover a un
partner a otro proveedor de identidad sea un cambio de fila y no un proyecto.

El punto de partida cambió el 8 de septiembre. Durante un mes la fase se
planificó sobre la premisa de que **Cognito imponía unicidad global de correo**,
deducida de `docs/guides/cognito-setup.md` y de los `admin_create_user` del
código. Comprobado contra el pool productivo (`us-east-1_IhHXuqCU9`), es falsa:
`UsernameAttributes` y `AliasAttributes` son `null`, y dos usuarios con el mismo
correo conviven — verificado por ejecución, no por lectura. La unicidad existía
porque **esta aplicación** pasa el correo como `Username`.

Eso deja la fase sin pool nuevo, sin migración perezosa y sin ventana de
convivencia. Lo que queda es lo que se hacía igual en cualquier escenario: la
abstracción. Este ADR fija sus cuatro decisiones de esquema, antes de que exista
código que dependa de ellas.

## Decisiones

### 1. `external_id` es el handle de autenticación, y no reemplaza a `cognito_sub`

Son dos identificadores distintos del mismo usuario, y ninguno se deduce del
otro:

| Columna | Qué es | Quién lo usa |
|---|---|---|
| `external_id` | El `Username` de Cognito: **con qué se autentica** | `initiate_auth`, `admin_*` |
| `cognito_sub` | El `sub`: **qué sujeto afirma el token** | `deps.py`, al verificar |

La tentación era renombrar `cognito_sub` a `external_id` —§5 lo describe como
«una migración trivial»— y habría dejado una columna llamada `external_id`
guardando el sujeto del token mientras el handle vivía en otra. Es justo la
confusión que la fase viene a deshacer.

`external_id` es **opaco por contrato**: correo para los usuarios que ya
existen, cuyo username en Cognito es inmutable; UUID para los que cree la
rebanada B. El código no lo parsea ni supone su forma. Un `if "@" in
external_id` es un bug, no una optimización.

Cuando exista un segundo proveedor, `cognito_sub` deberá llamarse
`provider_subject`. Ese renombre es de la rebanada B o posterior, y no antes:
hoy no hay nada que abstraer y el nombre actual dice la verdad.

### 2. La marca vive en la fila del usuario, y `NULL` es la marca por defecto

`UNIQUE(brand_account_id, email)` (§5) necesita la marca en `users`. Es
derivable —organización → cuenta → raíz de su `account_path`— pero una
restricción no puede depender de un JOIN.

**`NULL` no significa «sin marca»: significa la marca por defecto**, la que se
sirve a cualquier `Host` que no resuelva a un `tenant_domains` verificado. Hoy
son todos los usuarios, porque no hay un solo dominio dado de alta.

La alternativa mecánica —rellenar con la raíz de la cuenta de cada usuario—
está **descartada**: ataría cada usuario existente a una marca que no existe,
sin dominio por el que entrar, y rompería su login el día que `/auth/login`
empiece a filtrar por marca. Y no hay una cuenta raíz de Geminis con la que
rellenarlos: que no la haya es deliberado (§23), porque si todas las marcas
colgaran de una, `account_path @> ARRAY[esa]` casaría con el sistema entero.

El día que la marca Geminis exista como cuenta con dominio propio, un `UPDATE`
de una línea convierte estos `NULL` en su id.

### 3. La unicidad se parte en dos índices parciales

```sql
uq_users_marca_correo              UNIQUE (brand_account_id, email)
                                   WHERE brand_account_id IS NOT NULL
uq_users_correo_marca_por_defecto  UNIQUE (email)
                                   WHERE brand_account_id IS NULL
```

Porque en Postgres dos `NULL` nunca chocan: un único índice sobre
`(brand_account_id, email)` dejaría a **todo el padrón actual** sin unicidad de
correo, en silencio y el mismo día del despliegue.

`UNIQUE NULLS NOT DISTINCT` haría lo mismo en un solo objeto. **Descartado**
porque exige PostgreSQL 15 o superior y la versión de producción no está
verificada desde aquí. Es exactamente la clase de deducción que costó el mes de
§5: el local es 15.7, y de ahí no se sigue nada sobre producción. Dos índices
parciales funcionan en cualquier versión y dicen en su nombre lo que cubren.

Se crean **antes** de quitar `users_email_key`, en la misma migración y en ese
orden: así no hay ni un instante en que la tabla quede sin cobertura.

### 4. El enrutamiento de proveedor va por cuenta, nunca por variable de entorno

`accounts.identity_provider` + `accounts.idp_config` (jsonb). El proveedor se
resuelve *antes* de autenticar, a partir de la marca. Si fuera global, mover a
un partner enterprise a WorkOS obligaría a mover a todos — y esa es la única
pérdida seria que asumió la opción B de §5, con esta salida ya diseñada.

`idp_config` lleva configuración, **nunca credenciales**: identificadores de
conexión y referencias a Secrets Manager. Un secreto en una columna `jsonb`
acaba en cada respaldo, en cada dump de soporte y en cada log de consulta lenta.

Ambas columnas y `users.identity_provider` llevan un `CHECK` con la lista de
proveedores que el código sabe manejar, hoy `('cognito')`. Ampliarla es una
migración de una línea; un texto libre invita a que alguien escriba `'workos'`
meses antes de que exista el código que lo entienda, y a que el login de esa
cuenta falle sin que nadie sepa por qué.

## Lo que sostiene la ventana entre los dos releases

La 028 viaja sola (§18): el código que la usa sale en el release siguiente.
Durante esa ventana, el código viejo sigue creando usuarios con el correo como
username y sin tocar `external_id`. Un trigger `BEFORE INSERT OR UPDATE` lo
rellena con el correo cuando viene vacío, que es exactamente lo que ese código
acaba de hacer contra Cognito. Sin él, los usuarios creados entre los dos
releases nacerían sin handle y la rebanada B tendría que salir a buscarlos.

El trigger **no** pisa un `external_id` explícito —la rebanada B escribe UUID y
gana—, y **no** sigue los cambios de correo: el username de Cognito es
inmutable, así que un usuario que cambia de dirección conserva el handle con el
que se autentica. Es la diferencia con el trigger de `account_path` de la 027,
que sí recalcula e ignora lo que traiga el `INSERT`: aquél ancla un invariante
de aislamiento, éste sólo rellena un hueco de transición. Se borra en la
migración *contract*.

## Consecuencias

- **La reversión puede ser imposible.** El `downgrade` repone `users_email_key`,
  y si para entonces dos marcas ya comparten un correo, esa unicidad ya no es
  cierta. La migración lo detecta y aborta con el recuento en el mensaje en vez
  de dejar la base a medias. Ventana de reversión segura: hasta el primer
  usuario duplicado, no hasta el despliegue siguiente.
- **Hay una premisa sobre datos que hay que comprobar antes de desplegar**: que
  el username de todo usuario existente sea su correo. Es cierto para los que
  creó esta aplicación; no lo es necesariamente para los creados a mano desde la
  consola. El paso 1 de `docs/runbooks/desplegar-identidad.md` lo comprueba
  contra el pool y trae el `UPDATE` que corrige los que no encajen.
- **El modelo `User` queda desalineado a propósito** hasta la rebanada B: declara
  `email` con `unique=True` y no conoce las columnas nuevas. El comparador de
  deriva no lo ve —sólo mira que el esquema tenga lo que los modelos esperan— y
  el harness de tests seguirá creando la unicidad global. Por eso los tests de
  esta migración corren sobre la base desechable con el esquema productivo, y no
  sobre `create_all()`.

## Referencias

- §5, §11 y §23 del documento de arquitectura white-label
- [ADR-006](006-camino-materializado-en-uuid.md) — el árbol sobre el que se
  apoya `brand_account_id`
- `docs/runbooks/desplegar-identidad.md`
- `app/db/migrations/versions/028_identidad_esquema.py`

## Registro de cambios

| Fecha | Versión | Cambios |
|-------|---------|---------|
| 2026-09-08 | 1.0 | Documento inicial |

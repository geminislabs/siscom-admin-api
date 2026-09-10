# Runbook — desplegar la migración de identidad (028)

**Estado:** escrita y probada en local contra el esquema productivo. **No se ha
desplegado.**

Corresponde a la **rebanada A de la Fase 3** (§5, §11 y §23 del documento de
arquitectura). Ningún modelo, endpoint ni servicio de este repositorio conoce
todavía las columnas que crea: es la mitad *expand* del expand/contract (§18).

**No es aditiva pura, y ahí está la diferencia con la 027**: quita
`users_email_key`, la unicidad global de correo. Ese es el punto entero de la
fase —dos personas distintas, una en cada marca, con el mismo correo— y es lo
que obliga a leer la sección de reversión antes de desplegar.

Decisiones y por qué:
[ADR-007](../architecture/adr/007-identidad-por-marca-y-handle-opaco.md).

---

## Qué añade

| Objeto | Qué es |
|---|---|
| `users.external_id` | `text NOT NULL`. El handle opaco ante el proveedor: el `Username` de Cognito |
| `users.identity_provider` | `text NOT NULL DEFAULT 'cognito'`, con `CHECK` |
| `users.brand_account_id` | `uuid NULL` FK a `accounts`, `ON DELETE RESTRICT`. **`NULL` = la marca por defecto** |
| `uq_users_marca_correo` | `UNIQUE (brand_account_id, email)` donde la marca está puesta |
| `uq_users_correo_marca_por_defecto` | `UNIQUE (email)` donde la marca es `NULL` |
| `uq_users_proveedor_external_id` | `UNIQUE (identity_provider, external_id)` |
| `users_identidad_before` | Trigger que rellena `external_id` mientras dure la ventana |
| `accounts.identity_provider` | `text NULL`, con `CHECK`. `NULL` = hereda el del despliegue |
| `accounts.idp_config` | `jsonb NOT NULL DEFAULT '{}'`. Configuración, nunca credenciales |

Y **quita** `users_email_key`.

`external_id` **no** reemplaza a `cognito_sub`: el primero es con qué se
autentica (el username), el segundo es qué sujeto afirma el token (el `sub`, lo
que compara `deps.py`). Ninguno se deduce del otro y los dos siguen haciendo
falta. Ver ADR-007 §1.

---

## Paso 1 — la comprobación previa, que no es opcional

La migración da por cierto que **el username de Cognito de todo usuario
existente es su correo**. Es cierto para los que creó esta aplicación: sus
`admin_create_user` pasan el correo como `Username`. No lo es necesariamente
para los creados a mano desde la consola.

Si algún usuario no encaja, la migración le pondrá un `external_id` que en
Cognito no existe, y **su login dejará de funcionar cuando salga la rebanada B**
— no hoy, lo que hace el fallo más difícil de atribuir.

Contra el pool productivo (`us-east-1_IhHXuqCU9`, `us-east-1`):

```bash
aws cognito-idp list-users \
  --user-pool-id us-east-1_IhHXuqCU9 \
  --region us-east-1 \
  --query 'Users[].{u:Username,e:Attributes[?Name==`email`]|[0].Value}' \
  --output json > /tmp/pool-usuarios.json

# los que no encajan: username distinto del correo, comparando en minúsculas
jq -r '.[] | select((.u|ascii_downcase) != ((.e//"")|ascii_downcase))
        | "\(.u)\t\(.e)"' /tmp/pool-usuarios.json
```

- **Sin salida** → adelante con el paso 2.
- **Con salida** → anota cada par `username / correo`. Son los usuarios a los
  que hay que corregirles el handle **después** de migrar, con el `UPDATE` del
  paso 3. No bloquean el despliegue, pero sí la rebanada B.

La AWS CLI v2 pagina `list-users` sola. Si se usa v1, hay que iterar con
`--pagination-token`.

> Esta comprobación existe por la lección de §5: la premisa que sostenía la fase
> entera se dedujo de la guía de setup y del código, que decían la verdad sobre
> lo que hace la aplicación, y de ahí se saltó a una afirmación sobre lo que
> impone el proveedor. Preguntarle al pool costaba tres comandos.

---

## Paso 2 — despliegue

```bash
alembic upgrade head
```

No necesita extensiones, ni privilegios que `siscom_migrator` no tenga, ni
ningún paso manual previo. `ADD COLUMN ... DEFAULT` no reescribe la tabla en
PostgreSQL 11+; los tres índices únicos sí toman un lock de escritura sobre
`users` mientras se construyen — sobre el padrón actual es cuestión de
segundos, y va dentro de la misma ventana del despliegue.

---

## Paso 3 — comprobación después

`GET /health` debe reportar la revisión nueva:

```json
{ "schema_revision": "028_identidad_esquema" }
```

Y los tres contadores, que deben dar `0, 0, 0`:

```sql
SELECT count(*) FILTER (WHERE external_id IS NULL)            AS sin_handle,
       count(*) FILTER (WHERE external_id <> email)           AS handle_distinto_del_correo,
       count(*) FILTER (WHERE brand_account_id IS NOT NULL)   AS con_marca
  FROM users;
```

- `sin_handle` — la columna es `NOT NULL`, así que sólo puede dar 0. Está para
  que el día que dé otra cosa se sepa que alguien la relajó.
- `handle_distinto_del_correo` — debe ser 0 **justo después de migrar**, porque
  todavía no existe la rebanada B que asigna UUID. Deja de ser 0 en cuanto salga,
  y entonces este contador ya no significa nada: es una foto del día del
  despliegue.
- `con_marca` — 0. Ninguna marca tiene dominio todavía, así que todos los
  usuarios viven en la marca por defecto.

Si el paso 1 devolvió usuarios descolocados, corrígelos ahora, uno por uno y con
el username que dijo el pool:

```sql
UPDATE users SET external_id = :username_del_pool WHERE email = :correo;
```

---

## Reversión

```bash
alembic downgrade -1
```

**Puede fallar a propósito, y esa es la parte que hay que entender antes de
desplegar.** El `downgrade` repone `users_email_key`, la unicidad global de
correo. Si para entonces dos marcas ya comparten uno, esa unicidad ya no es
cierta y reponerla exigiría borrar usuarios: la migración lo detecta, aborta con
el recuento en el mensaje y no deja la base a medias.

> La ventana de reversión segura no llega hasta el despliegue siguiente: llega
> hasta el primer correo duplicado entre marcas. Mientras la rebanada B no exista
> y ningún partner tenga dominio, no puede haber ninguno.

Si hiciera falta revertir con duplicados ya creados, no es un `downgrade`: es
una decisión de producto sobre qué credencial sobrevive, y hay que tomarla antes
de tocar el esquema.

---

## Lo que esta migración deja abierto

- **La rebanada B** —interfaz `IdentityProvider`, `CognitoIdentityProvider`,
  username UUID para los usuarios nuevos, resolución de marca en `/auth/login`,
  selector de cuenta— va en el release siguiente y no trae migraciones.
- **`cognito_sub` conserva su nombre.** Pasará a `provider_subject` cuando exista
  un segundo proveedor, no antes: hoy no hay nada que abstraer y el nombre dice
  la verdad.
- **El modelo `User` queda desalineado a propósito**: sigue declarando `email`
  con `unique=True` y no conoce las columnas nuevas. El comparador de deriva no
  lo ve, porque sólo mira que el esquema tenga lo que los modelos esperan. Lo
  alinea la rebanada B.
- **El trigger `users_identidad_before` es de transición.** Existe para que los
  usuarios creados por el código viejo entre los dos releases no nazcan sin
  handle. Se borra en la migración *contract*, cuando toda alta pase por el
  proveedor de identidad.
- **Las plantillas de SES por marca** siguen sin empezar. El envío por SES ya
  existe (`app/services/notifications.py`); falta parametrizarlo por tenant, y
  no necesita esquema nuevo hasta que se decida dónde vive el remitente de cada
  marca.

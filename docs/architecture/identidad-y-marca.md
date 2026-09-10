# Identidad y marca

Cómo se identifica a un usuario en siscom-admin-api, y qué cambia cuando el
mismo despliegue atiende a varias marcas.

> **Estado (8 de septiembre de 2026).** Lo que describe este documento está en
> el **esquema** (migración `028_identidad_esquema`, Fase 3 rebanada A). El
> **código todavía no lo usa**: `/auth/login` sigue buscando `User.email` sin
> marca y creando usuarios de Cognito con el correo como username. La rebanada B
> es la que conecta las dos cosas. Cada sección marca qué parte ya existe y cuál
> no, porque leer esto como si estuviera todo construido lleva a escribir código
> que no funciona.

---

## 1. El problema

Hasta ahora un correo identificaba a una persona en todo el sistema:
`users.email` era `UNIQUE` global. Con una sola marca eso es correcto y barato.

Con varias marcas deja de serlo. La misma persona puede ser cliente de dos
proveedores de rastreo distintos —Mero Mero y otro partner— y esperar tener
cuenta en los dos, con el mismo correo, sin que ninguno sepa del otro. El correo
deja de ser identidad global y pasa a ser **identidad dentro de una marca**.

---

## 2. Los dos identificadores, que no son el mismo

Es la confusión que más código rompe, así que va primero.

| Columna | Qué guarda | Quién lo usa | Ejemplo |
|---|---|---|---|
| `users.external_id` | El **handle** con el que se autentica: el `Username` de Cognito | `initiate_auth`, `admin_*` | `jesus@ejemplo.com` (usuario viejo) · `9f1c…` (usuario nuevo) |
| `users.cognito_sub` | El **sujeto** que afirma el token: el claim `sub` | `deps.py`, al verificar un JWT | `a1b2c3d4-…` |

En Cognito son dos identificadores distintos del mismo usuario y **ninguno se
deduce del otro**. Un usuario cuyo username es su correo tiene, además, un `sub`
que no se parece en nada.

Por eso `external_id` **no** reemplaza a `cognito_sub` y esta fase no lo
renombra. Cuando exista un segundo proveedor, `cognito_sub` pasará a llamarse
`provider_subject`; hoy el nombre dice la verdad y cambiarlo sólo añadiría
ruido. Ver [ADR-007](adr/007-identidad-por-marca-y-handle-opaco.md) §1.

### `external_id` es opaco

Su forma depende de cuándo se creó el usuario:

- **Usuarios anteriores a la Fase 3**: su correo. El username de Cognito es
  inmutable, así que se quedan con el que tienen para siempre.
- **Usuarios nuevos** (a partir de la rebanada B): un UUID.

**El código no puede parsearlo ni suponer su forma.** Un `if "@" in
external_id` es un bug, no una optimización. Si hace falta saber algo del
usuario, se consulta la fila, no el handle.

> **El usuario nunca ve ni elige un username.** Sigue entrando con su correo y
> su contraseña. El handle es interno.

---

## 3. La marca de una credencial

`users.brand_account_id` apunta a la cuenta (`accounts`) dueña de la
credencial. Es la marca por la que ese usuario entra.

**`NULL` no significa «sin marca»: significa la marca por defecto** — la que se
sirve a cualquier `Host` que no resuelva a un dominio verificado en
`tenant_domains`. Hoy todos los usuarios están así, porque no hay ningún dominio
de partner dado de alta.

No se rellenó con la raíz de la cuenta de cada usuario, que sería la traducción
mecánica: eso los ataría a una marca que no tiene dominio por el que entrar, y
les rompería el login en cuanto `/auth/login` empiece a filtrar por marca.
Tampoco existe una cuenta raíz de Geminis de la que colgar a todos, y es
deliberado: si todas las marcas colgaran de una, `account_path @> ARRAY[esa]`
casaría con el sistema entero y habría un id que significa «todo».

El día que la marca Geminis exista como cuenta con dominio propio, convertir
esos `NULL` en su id es un `UPDATE` de una línea.

### De dónde sale la marca de una petición

```
Host: meromero.com
   │
   ▼
tenant_domains (hostname UNIQUE, status = 'VERIFIED')
   │
   ▼
accounts.id  ──►  la marca: logo, colores, textos legales, y el
                  brand_account_id contra el que se busca la credencial
```

> **El `Host` resuelve apariencia y nunca autoriza.** Llega en la caja que mande
> el cliente. Que alguien mande `Host: meromero.com` a mano no le da acceso a
> nada: los datos los determina la identidad autenticada y su subárbol
> (`account_path`), no la cabecera. Son dos resoluciones independientes y
> confundirlas es el bug clásico de estas plataformas.

Sólo se sirven dominios `VERIFIED`. Uno en `PENDING` lo puede reclamar
cualquiera hasta que demuestre control por DNS.

---

## 4. El esquema

### `users`

| Columna | Tipo | Notas |
|---|---|---|
| `external_id` | `text NOT NULL` | El handle. Ver §2 |
| `identity_provider` | `text NOT NULL DEFAULT 'cognito'` | `CHECK` sobre los proveedores que el código conoce |
| `brand_account_id` | `uuid NULL` → `accounts.id` | `ON DELETE RESTRICT`. `NULL` = marca por defecto |
| `cognito_sub` | `text NULL` | Sigue donde estaba. Es el sujeto del token |
| `email` | `text NOT NULL` | **Ya no es único global** |

### `accounts`

| Columna | Tipo | Notas |
|---|---|---|
| `identity_provider` | `text NULL` | `NULL` = hereda el proveedor por defecto del despliegue |
| `idp_config` | `jsonb NOT NULL DEFAULT '{}'` | Configuración de la conexión. **Nunca credenciales** |

El enrutamiento va **por cuenta y no por variable de entorno**: si fuera
global, mover a un partner enterprise a WorkOS obligaría a mover a todos. En
`idp_config` van identificadores de conexión y referencias a Secrets Manager; un
secreto ahí dentro acabaría en cada respaldo, en cada dump de soporte y en cada
log de consulta lenta.

---

## 5. La unicidad, que es el punto de la fase

`users_email_key` —la unicidad global de correo— **ya no existe**. En su lugar
hay dos índices únicos parciales que se reparten la tabla:

```sql
uq_users_marca_correo              UNIQUE (brand_account_id, email)
                                   WHERE brand_account_id IS NOT NULL
uq_users_correo_marca_por_defecto  UNIQUE (email)
                                   WHERE brand_account_id IS NULL
```

Uno solo no habría bastado: en Postgres dos `NULL` nunca chocan, así que un
índice sobre `(brand_account_id, email)` a secas habría dejado a **todo el
padrón actual** sin unicidad de correo, en silencio y el mismo día del
despliegue.

Y un tercero para el handle:

```sql
uq_users_proveedor_external_id     UNIQUE (identity_provider, external_id)
```

Único **dentro de su proveedor**, no globalmente: el día que una marca se enrute
a otro IdP, nada impide que allí exista un handle que en Cognito ya se use.

### Lo que esto significa para quien escribe consultas

```python
# MAL — asume que el correo identifica a una persona
user = db.query(User).filter(User.email == email).first()

# BIEN — el correo identifica dentro de una marca
user = (
    db.query(User)
    .filter(User.email == email, User.brand_account_id == marca_id)
    .first()
)
```

Con `marca_id = None` para la marca por defecto, que en SQLAlchemy es
`User.brand_account_id.is_(None)`, no `== None`.

> **Hoy `/auth/login` todavía hace la consulta de arriba, la mala.** Sigue
> siendo correcta mientras ningún usuario tenga marca, y deja de serlo el día
> que el primer partner tenga dominio. Lo cambia la rebanada B.

---

## 6. El trigger de transición

`users_identidad_before` (`BEFORE INSERT OR UPDATE OF external_id, email`)
rellena `external_id` con el correo cuando el alta viene sin él.

Existe porque la migración viaja un release antes que el código que la usa
(*expand/contract*): durante esa ventana el código viejo sigue creando usuarios
con el correo como username y sin tocar la columna nueva. Sin el trigger,
nacerían sin handle.

Dos cosas que **no** hace, y las dos importan:

- **No pisa un `external_id` explícito.** La rebanada B escribe UUID y gana. Es
  la diferencia con el trigger de `account_path` de la 027, que sí recalcula e
  ignora lo que traiga el `INSERT`: aquél ancla un invariante de aislamiento,
  éste sólo rellena un hueco de transición.
- **No sigue los cambios de correo.** El username de Cognito es inmutable, así
  que un usuario que cambia de dirección conserva el handle con el que se
  autentica. Si el trigger lo siguiera, el primer cambio de correo lo dejaría
  autenticándose contra un username que no existe en el pool.

Se borra en la migración *contract*, cuando toda alta pase por el proveedor de
identidad.

---

## 7. El pool de Cognito, y una premisa que resultó falsa

**Un solo pool para todas las marcas, con username UUID.** El productivo es
`us-east-1_IhHXuqCU9` (`us-east-1`, creado el 2025-10-20).

Durante un mes se planificó esta fase creyendo que **Cognito imponía unicidad
global de correo**, lo que habría obligado a crear un pool nuevo y a migrar a
todos los usuarios. Comprobado contra el pool, es falso:

```
UsernameAttributes: null
AliasAttributes:    null
```

Cognito no obliga a nada. La unicidad de correo existía porque **esta
aplicación** pasa el correo como `Username`. Verificado además por ejecución:
dos usuarios con el mismo atributo `email` y usernames distintos se crean sin
problema, con `sub` independientes.

De ahí que la fase no lleve pool nuevo, ni migración perezosa, ni ventana de
convivencia. Migrar a los usuarios existentes a username UUID pasa de requisito
a higiene, y probablemente no se haga nunca: sus usernames son inmutables y no
colisionan con nadie.

> **La lección no es sobre Cognito.** La premisa se dedujo de
> `docs/guides/cognito-setup.md` y de los `admin_create_user` del código, que
> decían la verdad sobre lo que hace la aplicación, y de ahí se saltó a una
> afirmación sobre lo que impone el proveedor. Preguntarle al pool costaba tres
> comandos y nadie los corrió en un mes.

**Consecuencia para quien cree un pool nuevo** (entorno de desarrollo, otra
región): configurarlo **sin** `email` como *username attribute* ni como *alias
attribute*. Un pool con el correo como alias vuelve a imponer unicidad global y
rompe el white-label. La guía de setup lo dice ahora en su paso 2.

---

## 8. Lo que traerá la rebanada B

Nada de esto existe todavía. Se lista para que nadie lo dé por hecho ni lo
construya por duplicado:

- **Interfaz `IdentityProvider`**, que no filtra Cognito. Nada de
  `ChallengeName` ni `AuthenticationResult` cruzando al dominio:
  `authenticate(brand_account_id, email, password)`, `create_credential(user)`,
  `reset_password_start / confirm`, `change_password`, `revoke_sessions`,
  `verify_token`.
- **`CognitoIdentityProvider`**, que saca boto3 de `app/api/v1/endpoints/auth.py`.
- **Username UUID** en las altas nuevas, con el correo como atributo normal.
- **Resolución de marca en `/auth/login`**: `Host` → marca → credencial por
  `(brand_account_id, email)` → `external_id` → autenticar.
- **Selector de cuenta** tras autenticar, para el usuario que pertenece a varias
  organizaciones de la misma marca.
- **Plantillas de SES por marca**. El envío ya existe
  (`app/services/notifications.py`); falta parametrizar remitente y contenido
  por tenant. Cognito no envía un solo correo en este sistema: todos los
  `admin_create_user` llevan `MessageAction="SUPPRESS"`.

---

## 9. Reglas para escribir código sobre esto

1. **La base de datos es la fuente de verdad de identidad y tenancy.** Cognito
   es un verificador de credenciales y nada más. Los atributos custom de Cognito
   son mutables desde las APIs de administración: cualquier claim de marca o de
   cuenta **se revalida contra Postgres**. Si se deja que el proveedor sea la
   verdad, deja de ser intercambiable.
2. **`external_id` es opaco.** No se parsea, no se compara con un correo, no se
   construye a mano.
3. **Un correo no identifica a una persona.** Toda búsqueda por correo lleva
   marca, o es un bug esperando al primer partner.
4. **El `Host` resuelve apariencia, nunca autorización.**
5. **`NULL` en `brand_account_id` es un valor con significado**, no un hueco:
   es la marca por defecto. Un `WHERE brand_account_id = :marca` con `:marca`
   nulo no devuelve nada.
6. **El proveedor se resuelve antes de autenticar**, a partir de la marca, y
   sale de `accounts.identity_provider` — nunca de una variable de entorno.

---

## 10. Referencias

| Documento | Qué aporta |
|---|---|
| [ADR-007](adr/007-identidad-por-marca-y-handle-opaco.md) | Las cuatro decisiones de esquema y sus alternativas descartadas |
| [ADR-006](adr/006-camino-materializado-en-uuid.md) | El árbol de cuentas sobre el que se apoya `brand_account_id` |
| [ADR-001](adr/001-account-organization-user-model.md) | El modelo Account / Organization / User de base |
| `docs/runbooks/desplegar-identidad.md` | Cómo se despliega la `028` y por qué su reversión es condicional |
| `docs/guides/cognito-setup.md` | Configuración del pool, con la advertencia del username |
| `app/db/migrations/versions/028_identidad_esquema.py` | El esquema, con el razonamiento en la cabecera |
| `tests/test_identidad_esquema.py` | Qué se comprueba, y sobre qué base |
| [modules/auth.md](modules/auth.md) · [modules/users.md](modules/users.md) | Los flujos que tocarán estas columnas |

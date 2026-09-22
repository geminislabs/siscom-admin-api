# Runbook — desplegar la migración de estado de usuario (029)

**Estado:** **desplegada** en `v1.32.2` el 21/09/2026, a la tercera — la `1.32.0` y la
`1.32.1` la anunciaron sin llegar a aplicarla. Resultado del despliegue al final.

Es **solo esquema y datos**: ningún modelo, endpoint ni servicio de este
repositorio lee todavía `users.status`. Mitad *expand* del expand/contract
(§18) — la migración viaja en un release y el código que la usa en el
siguiente.

Contexto y decisiones: **§26 del documento de arquitectura**.

---

## Por qué existe

Hoy no hay forma de dar de baja a un usuario, y eso produce un callejón sin
salida **que ya ocurre en producción**:

1. Un admin quita a alguien de la organización (`DELETE /{org}/users/{user_id}`).
   Se borra **la membresía**; la fila de `users` sobrevive con su correo y su
   credencial.
2. Meses después lo vuelven a invitar: `invite_user` busca por correo
   (`users.py:82`), encuentra la fila y responde **400**.
3. No hay salida por la API: no existe ningún endpoint que borre un usuario, y
   no había columna de estado. Sólo se arreglaba con SQL a mano.

Y **relajar la comprobación no era una opción**: los índices de la 028
(`uq_users_marca_correo`, `uq_users_correo_marca_por_defecto`) no filtran por
estado, así que aunque la aplicación dejara pasar el alta, Postgres la rechaza.
La respuesta correcta es **reactivar la fila**, no crear otra — que además
conserva el handle de Cognito, inmutable y todavía válido.

---

## Qué añade

| Objeto | Qué es |
|---|---|
| `users.status` | `text NOT NULL DEFAULT 'ACTIVE'` |
| `ck_users_status` | `CHECK (status IN ('ACTIVE','INACTIVE'))` |
| *(datos)* | La membresía `owner` de un master que no la tenga — **hoy: cero filas**, ver abajo |

**Sólo dos valores, a propósito.** Añadir `SUSPENDED` o `PENDING` ahora sería
sembrar códigos sin semántica acordada — lo mismo que la 027 evitó al no sembrar
`self_signup_mode`. Cuando el cierre de cuentas defina más estados, se añaden con
su `CHECK`.

---

## El relleno, y la premisa que resultó falsa

`OrganizationService.get_user_role` resuelve por membresía, pero tiene un
*fallback* heredado (`app/services/organization.py:78-81`): sin membresía, si
`user.organization_id` coincide y `user.is_master` es cierto, devuelve **OWNER**.

Ese *fallback* es la segunda fuente de verdad sobre «qué rol tiene esta persona
aquí», y produce un fallo propio: **a un master al que le borran la membresía no
se le quita el rol**. La salida limpia no es añadirle una condición sino
quitarlo. Lo que se creía es que para poder quitarlo había que darle su
membresía explícita a quien dependiera de él. Resultó que no hay nadie así.

> ### ⚠️ Medido el 20/09, y **mal interpretado** hasta el 21
>
> **Siete usuarios** con `is_master` y sin membresía OWNER, los siete sin ningún
> evento `org_user_removed`. De ahí se concluyó que eran **masters heredados**,
> de antes de que `organization_users` existiera.
>
> **Era falso, y lo destapó el despliegue de `v1.32.1`** con un
> `ForeignKeyViolation`: al medir los huérfanos salieron **exactamente los mismos
> siete**. La causa es circular — **no tienen membresía porque su organización no
> existe**: `organization_users.organization_id` tiene FK a `organizations`, así
> que esa fila nunca pudo crearse.
>
> Se dijo además que una de ellas era la cuenta del propio Jesús y que quitar el
> *fallback* sin rellenar le habría costado el OWNER de su organización.
> **También falso**: su organización no existe, así que el *fallback* sólo le da
> OWNER de algo que no está.
>
> **Consecuencia: el relleno inserta cero filas, y el *fallback* se puede borrar
> sin él** — lo único que sostiene son huérfanos.

La consulta, por si hay que repetirla en otro entorno:

```sql
SELECT u.id, u.email, u.is_master, u.organization_id,
       (SELECT max(e.created_at)
          FROM account_events e
         WHERE e.event_type = 'org_user_removed'
           AND e.target_id  = u.id) AS removido_en
FROM users u
WHERE u.is_master
  AND NOT EXISTS (
        SELECT 1 FROM organization_users ou
         WHERE ou.user_id         = u.id
           AND ou.organization_id = u.organization_id
           AND ou.role            = 'owner');
```

Esa consulta **no distingue huérfanos**, que es exactamente el error que costó
un despliegue. Para separarlos:

```sql
-- los que NO tienen organización: huérfanos, no se rellenan nunca
SELECT count(*) FROM users u
WHERE u.organization_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM organizations o WHERE o.id = u.organization_id);
```

- **Sin organización** → huérfano. El `INSERT` lo excluye con su `EXISTS`, y no
  hay membresía posible: la FK de `organization_users` lo impediría igual.
- **Con organización y `removido_en` nulo** → se rellena.
- **Con organización y `removido_en` con fecha** → lo sacaron adrede. No se
  rellena.

**El filtro por `account_events` se conserva aunque hoy no excluya a nadie.**
Cuesta un `NOT EXISTS` y hace la migración auto-correctiva: si entre la medición
y el despliegue alguien quita a un master a propósito, el relleno no le devuelve
el rol en silencio. Una migración que depende de que los datos no se muevan entre
que se miden y se aplica es una migración que miente.

**El `NOT EXISTS` de membresía no filtra por rol**, a propósito. La consulta de
arriba sí lo hace, pero insertar con ese criterio podría crear una segunda fila
para un usuario que ya tiene membresía con otro rol y violar `uq_org_user`. Quien
tenga membresía explícita —sea cual sea su rol— ya resuelve por ella y el
*fallback* no le afecta: se deja como está.

---

## Reversión

`downgrade` quita `ck_users_status` y la columna. **No toca las membresías que el
relleno pudiera haber creado**, y no por descuido: no conceden nada nuevo,
materializan un rol que el *fallback* ya daba. Revertir la columna no es razón
para quitárselo.

Hoy la cuestión es teórica —el relleno inserta cero filas— pero la regla queda
escrita y con test
(`test_segundo_ciclo_no_borra_las_membresias_ni_las_duplica`), para que si alguien
añade un `DELETE` «por simetría» se vea en CI y no en producción.

Rollback completo del release: redesplegar el tag anterior. La columna sobra
para el código viejo, que no la menciona.

---

## Verificación tras desplegar

**1 · Las tres señales del paso 6 de `docs/RELEASE.md`**

- `Running upgrade 028_identidad_esquema -> 029_estado_de_usuario`, **una sola vez**.
- Credencial `siscom_migrator`.
- `/health` con `schema_revision: 029_estado_de_usuario`.

**2 · Los contadores de alarma** — los tres tienen que dar **0**:

```sql
-- a) masters con organización REAL, sin membresía en ella
--    0 = el fallback de is_master ya no sostiene a nadie con acceso efectivo,
--    y se puede borrar. El EXISTS es lo que tumbó la v1.32.1: sin él, entran
--    los huérfanos, que no pueden tener membresía porque su organización no está
SELECT count(*) FROM users u
WHERE u.is_master
  AND u.organization_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM organizations o
               WHERE o.id = u.organization_id)
  AND NOT EXISTS (SELECT 1 FROM organization_users ou
                   WHERE ou.user_id = u.id
                     AND ou.organization_id = u.organization_id)
  AND NOT EXISTS (SELECT 1 FROM account_events e
                   WHERE e.event_type = 'org_user_removed'
                     AND e.target_id  = u.id);

-- b) usuarios sin estado (imposible: NOT NULL, pero cuesta nada mirarlo)
SELECT count(*) FROM users WHERE status IS NULL;

-- c) membresías duplicadas para el mismo (organización, usuario)
SELECT count(*) FROM (
  SELECT organization_id, user_id FROM organization_users
   GROUP BY 1, 2 HAVING count(*) > 1) d;
```

**3 · Cuántas membresías creó el relleno** — informativo. **Debe ser `0`.**

No es que el relleno falle: es que **no hay a quién rellenar**. Los siete que se
creían masters heredados resultaron ser huérfanos, y el `EXISTS` los excluye
correctamente. Si aquí saliera un número distinto de cero, significa que apareció
un master con organización real y sin membresía — legítimo, pero conviene mirar
de dónde salió.

```sql
SELECT count(*) FROM organization_users ou
 JOIN users u ON u.id = ou.user_id AND u.organization_id = ou.organization_id
 WHERE u.is_master AND ou.role = 'owner'
   AND ou.created_at > now() - interval '1 hour';
```

**4 · Los huérfanos** — informativo, y **no es un cero**: al 21/09/2026 son **7**.

Esta release **no los toca**. El contador está aquí para que el número no se
mueva sin que nadie lo note, y porque resolverlos es el trabajo que viene después
— con la columna `status` que esta migración añade, no borrando filas: veinte
claves foráneas referencian `users`, varias con `ON DELETE CASCADE` hacia
`mobility.devices`, `team.members`, `user_units` y `user_devices`.

```sql
SELECT count(*) FROM users u
WHERE u.organization_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM organizations o
                   WHERE o.id = u.organization_id);
```

**5 · Que la columna llegó** — todos deben salir `ACTIVE`:

```sql
SELECT status, count(*) FROM users GROUP BY 1;
```

---

## Resultado del despliegue del 21/09/2026

Las tres señales del paso 6 salieron: `Running upgrade 028_identidad_esquema ->
029_estado_de_usuario` **una sola vez**, con la credencial `siscom_migrator`, y
`/health` respondiendo `schema_revision: 029_estado_de_usuario`.

Los contadores, todos medidos contra producción el 21/09/2026 — (3), (4) y (5)
durante el despliegue, (a), (b) y (c) esa misma noche:

| Contador | Esperado | Medido | Lectura |
| --- | --- | --- | --- |
| **(a)** masters con organización real y sin membresía | `0` | **`0`** | El *fallback* de `is_master` no sostiene el acceso de nadie. **Se puede borrar** |
| **(b)** usuarios con `status IS NULL` | `0` | **`0`** | La columna es `NOT NULL`; confirmado, no deducido |
| **(c)** membresías duplicadas por (organización, usuario) | `0` | **`0`** | |
| **(3)** membresías creadas por el relleno | `0` | **`0`** | No hay a quién rellenar, y nunca lo hubo: es lo que tumbó la `1.32.1` |
| **(4)** huérfanos | informativo | **`7`** | Sigue abierto. Se resuelven **desactivándolos**, no borrándolos |
| **(5)** reparto de `status` | todo `ACTIVE` | **`ACTIVE: 23`** | Sin otros valores: la columna llegó y el *default* se aplicó a toda la tabla |

**Dos cosas que este corte deja dichas y conviene no perder.** La primera es que
**(a) = 0 es lo que autoriza** borrar el *fallback* de `is_master` en
`OrganizationService.get_user_role` — el punto que abre el release siguiente. La
segunda es la proporción: **7 huérfanos sobre 23 usuarios**, casi un tercio de la
tabla, y es la línea base contra la que se mide que ese número no crezca.

---

## Lo que viene en el release siguiente

El código que usa esta columna, y que es donde el fallo vivo se cierra de verdad:

- `invite_user` y `accept_invitation` **reactivan** la fila inactiva en vez de
  rechazar el alta.
- `remove_user_from_organization` marca la fila `INACTIVE` además de borrar la
  membresía.
- `admin_disable_user` en Cognito como refuerzo — **la columna es el dato, el
  proveedor es la defensa en profundidad, nunca al revés**.
- **Se borra el *fallback* de `is_master`** en
  `OrganizationService.get_user_role`, que es lo que el contador (a) autoriza.

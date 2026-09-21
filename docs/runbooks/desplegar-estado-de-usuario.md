# Runbook — desplegar la migración de estado de usuario (029)

**Estado:** escrita. **No se ha desplegado.**

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
| *(datos)* | La membresía `owner` que le falta a cada master heredado |

**Sólo dos valores, a propósito.** Añadir `SUSPENDED` o `PENDING` ahora sería
sembrar códigos sin semántica acordada — lo mismo que la 027 evitó al no sembrar
`self_signup_mode`. Cuando el cierre de cuentas defina más estados, se añaden con
su `CHECK`.

---

## El relleno, y por qué no es opcional

`OrganizationService.get_user_role` resuelve por membresía, pero tiene un
*fallback* heredado (`app/services/organization.py:78-81`): sin membresía, si
`user.organization_id` coincide y `user.is_master` es cierto, devuelve **OWNER**.

Ese *fallback* es la segunda fuente de verdad sobre «qué rol tiene esta persona
aquí», y produce un fallo propio: **a un master al que le borran la membresía no
se le quita el rol**. La salida limpia no es añadirle una condición sino
quitarlo — y para poder quitarlo, todo usuario que hoy dependa de él necesita su
membresía explícita.

> ### ✅ Medido contra producción el 20 de septiembre de 2026
>
> **Siete usuarios** con `is_master` y sin membresía OWNER en su organización, y
> los siete **sin ningún evento `org_user_removed`** en `account_events`. Son
> masters heredados, de antes de que `organization_users` existiera; ninguno es
> alguien a quien sacaron a propósito.
>
> Uno de ellos es la cuenta del propio Jesús: **quitar el *fallback* sin este
> relleno le habría costado el OWNER de su organización.** La medición se pagó
> sola.

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

- `removido_en` **nulo** → heredado. Se rellena.
- `removido_en` **con fecha** → lo sacaron adrede. **No se rellena**, y el
  `INSERT` de la migración ya lo excluye.

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

`downgrade` quita `ck_users_status` y la columna. **No toca las membresías**, y
no por descuido: el relleno no concede nada nuevo, materializa el rol que esas
siete personas ya tienen hoy a través del *fallback*. Revertir la columna no es
razón para quitárselo, y borrarlas las dejaría peor que antes de la migración.

El relleno es, en ese sentido, **irreversible a propósito**. Está fijado con un
test (`test_segundo_ciclo_no_borra_las_membresias_ni_las_duplica`), para que si
alguien añade un `DELETE` «por simetría» se vea en CI y no en producción.

Rollback completo del release: redesplegar el tag anterior. La columna sobra
para el código viejo, que no la menciona.

---

## Verificación tras desplegar

**1 · Las tres señales del paso 6 de `docs/RELEASE.md`**

- `Running upgrade 028_identidad_esquema -> 029_estado_de_usuario`, **una sola vez**.
- Credencial `siscom_migrator`.
- `/health` con `schema_revision: 029_estado_de_usuario`.

**2 · Los contadores de esta migración** — los tres tienen que dar **0**:

```sql
-- a) masters sin ninguna membresía en su propia organización
--    (0 = el fallback de is_master ya no sostiene a nadie, y se puede borrar)
SELECT count(*) FROM users u
WHERE u.is_master
  AND u.organization_id IS NOT NULL
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

**3 · Cuántas membresías creó el relleno** — informativo, no un contador de
alarma. Debería ser **7**:

```sql
SELECT count(*) FROM organization_users ou
 JOIN users u ON u.id = ou.user_id AND u.organization_id = ou.organization_id
 WHERE u.is_master AND ou.role = 'owner'
   AND ou.created_at > now() - interval '1 hour';
```

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

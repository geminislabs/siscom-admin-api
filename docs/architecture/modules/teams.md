# Módulo: Teams

## 📌 Descripción

Grupos de personas (familia, amigos, flotilla de trabajo, viaje, emergencia)
que comparten ubicación entre sí según reglas de visibilidad declaradas por
rol. Es un módulo de **personas**, distinto del módulo de `units`/`devices`
(vehículos): un usuario puede pertenecer a varios teams, y lo que un team
resuelve es quién ve la ubicación de quién dentro del grupo — no a qué
unidad vehicular tiene acceso.

**Estado (30/09/2026): completo del lado de "declarar reglas", en cero del
lado de "hacerlas cumplir".** Ver [Consideraciones](#️-consideraciones) — es
la nota más importante de este documento.

---

## 👤 Actor

- Usuario autenticado vía Cognito (`GET/POST/PATCH/DELETE /api/v1/teams/*`)
- Nadie sin cuenta: no hay acceso público excepto el detalle de una
  invitación por su token (`GET /api/v1/team-invites/{token}`, antes de
  aceptarla)
- Servicio interno vía PASETO, sólo lectura de snapshot
  (`GET /internal/teams/{id}/snapshot`) — pensado para GAC, sin consumidor
  confirmado todavía

---

## 🔌 Recursos consumidos

### 🔹 PostgreSQL — esquema `team`

| Tabla | Migración | Uso |
|-------|-----------|-----|
| `teams` | `016_team_core` | El grupo. Cuelga de `account_id`, no de `organization_id` — un team puede agrupar personas de varias organizaciones de la misma cuenta |
| `members` | `016_team_core` | Pertenencia y rol (`OWNER`/`ADMIN`/`MEMBER`/`EMPLOYEE`/`DEPENDENT`/`VIEWER`/`EMERGENCY_CONTACT`/`GUEST`) |
| `visibility_rules` | `016_team_core` | Quién (`subject_role`) es visible para quién (`viewer_role`), con `access_mode` (`ALWAYS`/`EMERGENCY_ONLY`) y ventanas horarias opcionales (`schedule`, JSONB) |
| `invites` | `017_team_invites` | Invitaciones por link: token de 256 bits, solo se persiste el SHA-256, `expires_at`, `max_uses`, `used_count` |
| `emergency_events` | `016_team_core` | Activación/resolución/cancelación de una emergencia dentro de un team |

### 🔹 Kafka (producer) — tópico `team-rules-updates`

**Variable:** `KAFKA_TEAM_RULES_TOPIC` (default: `team-rules-updates`).
**Productor:** `TeamRulesKafkaProducer` (`app/services/messaging/kafka_producer.py`).
Se publica un evento en **cada** mutación del módulo — teams, members,
invites, visibility rules y emergency events comparten el mismo tópico.

**Schema del evento:**

```json
{
  "event_id": "uuid",
  "event_type": "TEAM_MEMBER_ADDED",
  "team_id": "uuid",
  "account_id": "uuid",
  "actor_user_id": "uuid",
  "occurred_at": "2026-09-30T12:00:00Z",
  "version": 1,
  "payload": { "member_id": "uuid", "user_id": "uuid", "role": "MEMBER" }
}
```

**`event_type` por origen:**

| Origen | Eventos |
|--------|---------|
| Team | `TEAM_CREATED`, `TEAM_UPDATED`, `TEAM_SUSPENDED`, `TEAM_ACTIVATED`, `TEAM_EXPIRED`, `TEAM_DELETED` |
| Members | `TEAM_MEMBER_ADDED`, `TEAM_MEMBER_UPDATED`, `TEAM_MEMBER_REMOVED`, `TEAM_MEMBER_JOINED` (al aceptar una invitación) |
| Invites | `TEAM_INVITE_CREATED`, `TEAM_INVITE_REVOKED` |
| Visibility rules | `VISIBILITY_RULE_CREATED`, `VISIBILITY_RULE_UPDATED`, `VISIBILITY_RULE_DELETED` |
| Emergency events | `EMERGENCY_STARTED`, `EMERGENCY_RESOLVED`, `EMERGENCY_CANCELLED` |

**Quién lo consume hoy: nadie.** Confirmado por Jesús el 30/09/2026 — la
implementación del lado consumidor nunca se terminó. No hay un segundo
servicio suscrito a `team-rules-updates`, y **tampoco lo consume nada dentro
de este mismo repo**: ver la sección de abajo.

---

## 🔁 Flujo funcional

### Crear un team (`POST /teams`)

```
1. Resuelve account_id desde la organización del usuario actual
   (Organization.account_id, con fallback a organization_id si la fila
   no existe — mismo patrón que usa add_member, ver abajo)
2. Crea el team, con el creador como OWNER en la misma transacción
3. Siembra las visibility_rules default según el tipo de team
   (FAMILY/FRIENDS/WORKFORCE/EMERGENCY/TRAVEL)
4. Publica TEAM_CREATED
```

### Agregar un miembro (`POST /teams/{id}/members`)

```
1. Exige que quien llama sea OWNER o ADMIN del team (require_role)
2. Valida que el usuario a agregar pertenezca a la misma cuenta que el
   team (TeamService.resolve_account_id) — arreglado el 30/09/2026, antes
   aceptaba cualquier users.id del sistema
3. Valida que no sea ya miembro, y que sólo un OWNER agregue a otro OWNER
4. Crea la membresía, con joined_at = ahora (sin invitación de por medio)
5. Publica TEAM_MEMBER_ADDED
```

**Nota abierta:** este alta es unilateral — a diferencia del flujo de
invites (abajo), la persona agregada no confirma nada. Ver
[Consideraciones](#️-consideraciones).

### Invitar por link (`POST /teams/{id}/invites` → `POST /team-invites/{token}/accept`)

```
1. OWNER/ADMIN genera un token aleatorio de 256 bits; solo se guarda su
   SHA-256, con expires_at y max_uses
2. Quien recibe el link ve el detalle público (GET /team-invites/{token},
   sin autenticación) y decide aceptar
3. accept_invite toma un SELECT ... FOR UPDATE sobre la invitación, así
   que el contador de usos no tiene carrera
4. Crea la membresía y publica TEAM_MEMBER_JOINED
```

### Emergencia (`POST /emergency-events`, `/resolve`, `/cancel`)

```
1. Cualquier miembro del team puede iniciar una emergencia
2. Mientras está ACTIVE, las visibility_rules con access_mode=
   EMERGENCY_ONLY deberían levantarse para los viewer_role configurados
   — hoy sólo existe la declaración de la regla, ver Consideraciones
3. Publica EMERGENCY_STARTED / EMERGENCY_RESOLVED / EMERGENCY_CANCELLED
```

---

## ⚠️ Consideraciones

**Las `visibility_rules` no filtran nada todavía, en ningún camino real.**
`app/services/access_control.py` (que decide qué unidades/ubicaciones puede
ver un sujeto) no importa ni referencia nada de `app.models.team` — su
`ScopeSubject` sólo conoce `organization_id` y `user_units` (asignación de
vehículos). El único punto de integración que existe es un gancho explícito
en `app/services/data_token_issuance.py::next_scope_boundary`:

```python
def next_scope_boundary(db: Session, subject: ScopeSubject) -> Optional[datetime]:
    """
    Punto de extensión para `team.visibility_rules`, cuyas ventanas horarias
    (`schedule`, JSONB) hacen que el alcance caduque solo con el paso del
    reloj. Hoy devuelve None —ningún cliente consume teams todavía— y el
    token usa el TTL máximo. Cuando teams entre, esta función es lo único
    que hay que implementar: el TTL adaptativo ya está cableado en
    `compute_expiry`.
    """
    return None
```

Mismo estado documentado en
[ADR-005](../adr/005-data-token-plano-de-datos.md#vigencia-adaptativa).

**Consecuencia práctica:** todo lo que hoy se puede hacer con Teams —crear
un team, invitar, agregar miembros, declarar reglas, disparar una
emergencia— es **puramente declarativo**. Ningún viewer ve la ubicación de
ningún subject por estar en el mismo team, consienta o no, porque nada
consulta `visibility_rules` para decidir qué devuelve un data token. El
hallazgo de que `add_member` no pide consentimiento (documentado en
`docs/security/threat-model.md`, sección de módulos sensibles) tiene por
eso **impacto real cero hoy** — se vuelve relevante el día que se conecte
el enforcement.

### Qué haría falta para que esto exista de verdad

Tres piezas, en el orden en que una depende de la anterior:

1. **Un consumidor de `team-rules-updates`.** Hoy no existe ninguno. El
   consumidor necesita materializar el estado (team → members → roles →
   visibility_rules activas) en algo consultable rápido — replicar la
   tabla, o mantener una proyección en Valkey/Redis como hace
   `app/services/scope_store.py` con los alcances de unidad.
2. **Que `access_control.accessible_refs` sepa preguntar por Teams.**
   `ScopeSubject` necesitaría un tercer eje además de
   `organization_id`/`user_id` — o una función paralela,
   `accessible_user_ids(db, subject)`, análoga a `accessible_unit_ids`, que
   devuelva qué usuarios (no qué unidades) puede ver un sujeto según sus
   membresías de team y las `visibility_rules` activas en ese momento
   (`access_mode`, `schedule`, y si hay una `emergency_event` ACTIVE que
   levante una regla `EMERGENCY_ONLY`).
3. **Implementar `next_scope_boundary`** para que el TTL del data token se
   acorte exactamente cuando una ventana horaria de `schedule` cierra o
   abre — el mecanismo (`compute_expiry`) ya existe y espera este dato.

Recién con las tres piezas tiene sentido resolver el consentimiento de
`add_member`: hoy sería arreglar un problema que no tiene ningún efecto
observable, y la forma correcta de resolverlo (¿la persona agregada debe
confirmar? ¿debe poder ver quién la agregó y a qué la expone?) depende de
cómo termine luciendo el enforcement real.

---

## 🧭 Relación C4 (preview)

- **Container:** SISCOM Admin API (FastAPI)
- **Consumes:** PostgreSQL (`schema=team`)
- **Produces:** Kafka (`team-rules-updates`) — sin consumidor confirmado
- **Consumed by:** ningún cliente todavía (ni Android, ni iOS, ni la web);
  la API interna (`/internal/teams/*`) está pensada para GAC pero tampoco
  tiene consumidor confirmado
- **Related:** [ADR-005 — Data token, plano de datos](../adr/005-data-token-plano-de-datos.md), `docs/security/threat-model.md` (módulos sensibles)

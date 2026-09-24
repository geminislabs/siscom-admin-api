# Snapshot del esquema de producción

Punto de partida para `scripts/verificar-deriva.py`. **No es la definición del
esquema** —esa es la cadena de alembic— sino una foto de dónde estaba producción
para poder reproducir las migraciones sobre algo real.

## Por qué existe

Comparar `SQLModel.metadata` contra una base construida con `create_all()` desde
esa misma metadata es tautológico: siempre sale vacío. La comparación solo dice
algo cuando el esquema viene de otro sitio.

Con este snapshot, la CI hace lo que producción hace: parte del esquema real,
aplica las migraciones y comprueba el resultado. Es la comprobación que habría
cantado la deriva de septiembre de 2026 en el PR que la introdujo, en vez de
descubrirse meses después por un dump pedido a mano.

## `deriva-conocida.toml`

La línea base de restricciones que lee `scripts/verificar-deriva.py`. **No es una
lista de cosas aceptadas**: es la fotografía de lo que hoy no coincide entre los
modelos y el esquema migrado, para que deje de ser invisible.

Falla en las dos direcciones, y la segunda es la que la mantiene honesta:

| Situación | Qué pasa |
|---|---|
| Aparece una divergencia que no está en la lista | La CI falla. O se arregla, o entra con su porqué |
| Una de la lista deja de ocurrir | La CI falla igual: hay que quitarla, porque una lista que no se poda deja de describir el presente |

Nació el 23/09/2026 con 32 entradas, al descubrir —poniendo la FK de
`users.organization_id`— que el comparador sólo miraba nombres de tablas y
columnas. Llevaba meses diciendo «sin deriva» con esa columna declarada
`NOT NULL` en el modelo y `NULL` en la base.

## Qué hay aquí

| Fichero | Origen |
|---|---|
| `00-preambulo.sql` | Escrito a mano: esquemas, extensiones, tipos ENUM y `set_updated_at()`, que el export no trae |
| `10-public.sql` | Export del 5/09/2026 — 73 tablas de `public` |
| `20-team.sql` | Export del 5/09/2026 — 5 tablas de `team` |
| `30-mobility.sql` | Export del 5/09/2026 — 3 tablas de `mobility` |
| `40-epilogo.sql` | `unified_sim_profiles`, derivada del modelo |

Corresponde a la revisión **`025_device_and_unit_refs`**, antes de la `026`. Eso
es deliberado: hace que `upgrade head` ejecute migraciones de verdad en vez de
ser un no-op.

## Limitaciones conocidas

El export salió de una herramienta gráfica, **no de `pg_dump --schema-only`**, y
eso se nota:

1. **No trae tipos, esquemas ni funciones.** Los repone `00-preambulo.sql`.
2. **No ordena por dependencias**: hay índices y restricciones que referencian
   tablas creadas más abajo. Por eso el verificador carga en dos pasadas.
3. **`unified_sim_profiles` no venía**, aunque existe en producción. Su DDL sale
   del modelo, así que **el comparador no puede detectar deriva sobre esa
   tabla** — la compara consigo misma. Hueco conocido, acotado a una tabla.
4. **Dos tablas no cargan**: escribe `DEFAULT 'UNKNOWN'::text` para columnas de
   tipo ENUM y Postgres lo rechaza con *"default expression is of type text"*.
   Afecta a `unit_fuel_profile` y `device_idle_activity`. **Ninguna de las dos
   está en los modelos**, así que no altera la comparación.
5. **No trae particiones hijas.** Fue lo que hizo que el ensayo de la `026` no
   detectara el fallo de propiedad de `trip_events`.

Las cinco desaparecen el día que el snapshot se regenere con `pg_dump`.

## Cómo refrescarlo

```bash
pg_dump --schema-only --no-owner --no-privileges \
  -h <host> -U <usuario> -d <base> > tests/schema/10-public.sql
```

Y actualizar `DRIFT_STAMP` en `scripts/verificar-deriva.py` a la revisión en la
que esté producción cuando se tome la foto.

**Cada cuánto**: no hay respuesta automática. Un snapshot viejo hace que la CI
pruebe contra un pasado, pero refrescarlo en cada release lo convierte en
ceremonia. La regla razonable es refrescarlo cuando se toque el esquema fuera de
alembic —que idealmente no pasa— o cuando el preámbulo empiece a acumular
parches. **Queda como decisión abierta.**

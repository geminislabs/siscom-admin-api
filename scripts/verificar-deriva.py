#!/usr/bin/env python3
"""
Comprueba que las migraciones llevan el esquema real al que los modelos esperan.

QUE HACE, Y POR QUE ASI
=======================
Carga en una base desechable el snapshot del esquema PRODUCTIVO
(`tests/schema/`), lo stampea en la revision que le corresponde, corre
`alembic upgrade head`, y compara el resultado contra `SQLModel.metadata`.

El punto es que la base NO se construye con `create_all()`. Comparar la
metadata contra una base hecha desde esa misma metadata es tautologico: siempre
sale vacio. Solo tiene sentido cuando el esquema viene de otro sitio — aqui, de
produccion mas las migraciones.

Es la comprobacion que habria cantado la deriva de septiembre de 2026 en el PR
que la introdujo, en vez de descubrirse meses despues por un dump pedido a mano:
tres tablas ausentes con endpoint vivo —una de ellas la del cobro— y siete
columnas que impedian consultar tres modelos centrales.

La maquinaria de la base desechable vive en `tests/esquema_desechable.py`, que
comparte con los tests que ejercitan objetos que solo crean las migraciones.

QUE COMPARA
===========
Dos cosas, y con dos criterios distintos:

1. **Presencia de tablas y columnas.** Cualquier ausencia es deriva y falla.
2. **Nulabilidad y claves foraneas**, contra la linea base de
   `tests/schema/deriva-conocida.toml`. Falla si aparece una divergencia que no
   esta en la lista **y tambien** si una de la lista deja de existir sin que
   nadie la quite — una linea base que no se poda deja de decir la verdad.

El punto 2 se anadio el 23/09/2026, al poner la FK de `users.organization_id`:
el comparador llevaba meses diciendo "sin deriva" mientras esa columna era
`NULL` sin restriccion y el modelo la declaraba `NOT NULL` con `ForeignKey`.
Comparaba nombres, no restricciones, y su verde se leia como "todo coincide".
Al mirarlo aparecieron **22 discrepancias de nulabilidad y 9 claves foraneas**
que el modelo declara y la base no tiene — entre ellas `units.organization_id`,
la otra mitad del predicado de aislamiento.

LO QUE ESTA COMPROBACION NO PRUEBA
==================================
Solo mira en una direccion: que el esquema contenga lo que los modelos esperan.
Una migracion que cree tablas que ningun modelo declara —el caso de la rebanada
A de la Fase 2, que es esquema sin modelos a proposito— pasa por aqui sin que
se revise nada suyo salvo que aplique sin error. Para eso estan los tests que
la ejercitan.

Tampoco mira tipos ni valores por defecto. Se puede anadir con el mismo patron
de linea base el dia que haga falta.

Uso:
    ./scripts/db-local.sh up
    python scripts/verificar-deriva.py

Sale con codigo 1 si hay deriva.
"""

import os
import sys
import tomllib
from pathlib import Path

from sqlalchemy import create_engine, inspect

# El script vive en scripts/, así que la raíz del repo no está en el path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.bootstrap_env import bootstrap_test_runtime  # noqa: E402

bootstrap_test_runtime()

from sqlmodel import SQLModel  # noqa: E402

from tests import esquema_desechable as desechable  # noqa: E402
from tests.esquema_desechable import ESQUEMAS  # noqa: E402

BASE_DERIVA = os.getenv("DRIFT_DB_NAME", "siscom_drift")
LINEA_BASE = (
    Path(__file__).resolve().parents[1] / "tests" / "schema" / "deriva-conocida.toml"
)


def _registrar_modelos() -> None:
    """Puebla SQLModel.metadata. Sin esto la comparacion es de cero contra cero.

    Importar `SQLModel` no registra nada: los modelos se registran al importarse
    sus modulos. Sin esta llamada el script decia "sin deriva" habiendo revisado
    cero tablas — un verde vacio, que es exactamente lo que viene a impedir.
    """
    import app.models  # noqa: F401
    from app.api.v1.endpoints.api_platform.models import (  # noqa: F401
        api_alert,
        api_key,
        api_limit,
        api_log,
        api_throttle,
        api_usage,
    )


def _restricciones(insp) -> tuple[list[str], list[str]]:
    """Divergencias de nulabilidad y claves foraneas ausentes, en texto estable.

    El formato de cada linea es el que se guarda en la linea base, asi que lo
    que se compara es exactamente lo que se lee en el fichero. Sin eso, la lista
    y el codigo se separan en cuanto alguien cambie el formato.
    """
    nulabilidad, claves = [], []

    for tabla in SQLModel.metadata.tables.values():
        esquema = tabla.schema or "public"
        if tabla.name not in insp.get_table_names(schema=esquema):
            continue

        reales = {c["name"]: c for c in insp.get_columns(tabla.name, schema=esquema)}
        for col in tabla.columns:
            real = reales.get(col.name)
            if real is None:
                continue  # lo reporta la comparacion de columnas
            if bool(col.nullable) != bool(real["nullable"]):
                dice_modelo = "NULL" if col.nullable else "NOT NULL"
                dice_base = "NULL" if real["nullable"] else "NOT NULL"
                nulabilidad.append(
                    f"{esquema}.{tabla.name}.{col.name}: "
                    f"modelo={dice_modelo} base={dice_base}"
                )

        en_la_base = {
            tuple(fk["constrained_columns"])
            for fk in insp.get_foreign_keys(tabla.name, schema=esquema)
        }
        for fk in tabla.foreign_keys:
            if (fk.parent.name,) not in en_la_base:
                claves.append(
                    f"{esquema}.{tabla.name}.{fk.parent.name} -> {fk.target_fullname}"
                )

    return sorted(nulabilidad), sorted(claves)


def _linea_base() -> tuple[set[str], set[str]]:
    if not LINEA_BASE.exists():
        return set(), set()
    datos = tomllib.loads(LINEA_BASE.read_text(encoding="utf-8"))
    return set(datos.get("nulabilidad", [])), set(datos.get("claves_foraneas", []))


def _revisar_restricciones(insp) -> int:
    """Compara contra la linea base. Devuelve 0 si no hay novedad."""
    nulabilidad, claves = _restricciones(insp)
    base_nul, base_fk = _linea_base()

    nuevas = sorted((set(nulabilidad) - base_nul) | (set(claves) - base_fk))
    # Una entrada que ya no es divergencia sigue en la lista: alguien la
    # arreglo y no la quito. Tambien falla, porque una linea base que no se poda
    # deja de decir la verdad — y la siguiente persona la leera como vigente.
    resueltas = sorted((base_nul - set(nulabilidad)) | (base_fk - set(claves)))

    print(
        f"\nRestricciones: {len(nulabilidad)} divergencias de nulabilidad y "
        f"{len(claves)} claves foraneas ausentes "
        f"({len(base_nul) + len(base_fk)} en la linea base)"
    )

    if not nuevas and not resueltas:
        print("Sin novedad respecto a la linea base.")
        return 0

    if nuevas:
        print(f"\nDERIVA NUEVA — {len(nuevas)} sin registrar\n")
        for x in nuevas:
            print(f"  {x}")
        print(f"\n  Si es deliberada, anadela a {LINEA_BASE.name} con su porque.")

    if resueltas:
        print(f"\nYA NO OCURREN — {len(resueltas)} que sobran en la linea base\n")
        for x in resueltas:
            print(f"  {x}")
        print(f"\n  Quitalas de {LINEA_BASE.name}: la lista describe el presente.")

    return 1


def _comparar() -> int:
    _registrar_modelos()
    if not SQLModel.metadata.tables:
        print("No se registro ningun modelo: la comparacion no probaria nada.")
        return 1
    eng = create_engine(desechable.url(BASE_DERIVA))
    insp_guardado = inspect(eng)
    try:
        existentes = {}
        for esquema in ESQUEMAS:
            for t in insp_guardado.get_table_names(schema=esquema):
                existentes[(esquema, t)] = {
                    c["name"] for c in insp_guardado.get_columns(t, schema=esquema)
                }

        resultado = _comparar_presencia(existentes, insp_guardado)
    finally:
        eng.dispose()
    return resultado


def _comparar_presencia(existentes, insp_guardado) -> int:

    faltan_tablas, faltan_columnas = [], []
    for tabla in SQLModel.metadata.tables.values():
        clave = (tabla.schema or "public", tabla.name)
        if clave not in existentes:
            faltan_tablas.append(f"{clave[0]}.{clave[1]}")
            continue
        faltan = [c.name for c in tabla.columns if c.name not in existentes[clave]]
        if faltan:
            faltan_columnas.append(
                f"{clave[0]}.{clave[1]}: {', '.join(sorted(faltan))}"
            )

    print(f"\nTablas del modelo revisadas: {len(SQLModel.metadata.tables)}")
    if not faltan_tablas and not faltan_columnas:
        print(
            "Sin tablas ni columnas ausentes: el esquema migrado tiene lo que los "
            "modelos nombran."
        )
        return _revisar_restricciones(insp_guardado)

    print(
        f"\nDERIVA — {len(faltan_tablas)} tablas y {len(faltan_columnas)} tablas con columnas faltantes\n"
    )
    for t in sorted(faltan_tablas):
        print(f"  falta la tabla   {t}")
    for c in sorted(faltan_columnas):
        print(f"  faltan columnas  {c}")
    print(
        "\nCausa habitual: un modelo cambio y no se escribio la migracion que lo "
        "acompana. La migracion viaja en el mismo PR que el modelo."
    )
    return 1


def main() -> int:
    from app.core.config import settings

    print(f"Base desechable: {BASE_DERIVA} en {settings.DB_HOST}:{settings.DB_PORT}")
    try:
        desechable.preparar(BASE_DERIVA)
    except RuntimeError as exc:
        print(f"\n{exc}")
        return 1

    print("\n4. Comparando modelos contra el esquema migrado")
    return _comparar()


if __name__ == "__main__":
    sys.exit(main())

"""Nada escribe las tablas del plano de control sin pasar por el ORM.

Los eventos de `control-plane-events` los emite un listener de la sesión
(`app/services/messaging/control_plane.py`) a partir de los objetos que toca
cada flush. Lo único que se lo salta es escribir sin objetos:
`query(Modelo).update()`, `query(Modelo).delete()`, `update(Modelo)` /
`delete(Modelo)` de SQLAlchemy Core, o SQL crudo. Esa escritura cambiaría la
base sin que ningún consumidor se enterara hasta su siguiente reinicio.

Hoy no hay ninguna. Si alguna vez hace falta, que sea consciente: este test
falla, y quien la escriba tiene que emitir a mano con
`control_plane.construir_eventos` + `control_plane.publicar`, o justificar la
excepción aquí.
"""

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "app"

MODELOS = {"OrganizationUser", "User", "UserUnit", "UnitDevice", "UserDevice", "Unit"}
TABLAS = (
    "users",
    "organization_users",
    "user_units",
    "unit_devices",
    "user_devices",
    "units",
)
SQL_QUE_ESCRIBE = re.compile(
    r"\b(UPDATE|DELETE\s+FROM|INSERT\s+INTO)\s+(public\.)?("
    + "|".join(TABLAS)
    + r")\b",
    re.IGNORECASE,
)

# Las migraciones escriben con SQL a propósito: cambian el esquema o hacen
# backfills de una vez, y los consumidores se reconstruyen desde las vistas al
# reiniciar después de un despliegue.
EXCLUIDOS = ("db/migrations/",)


def _ficheros():
    for ruta in sorted(RAIZ.rglob("*.py")):
        relativa = ruta.relative_to(RAIZ).as_posix()
        if not any(relativa.startswith(e) for e in EXCLUIDOS):
            yield relativa, ruta.read_text(encoding="utf-8")


def _query_de_modelo(nodo) -> str | None:
    """Si `nodo` es una cadena que empieza en `x.query(Modelo, ...)`, el modelo."""
    while isinstance(nodo, ast.Call | ast.Attribute):
        if (
            isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Attribute)
            and nodo.func.attr == "query"
            and nodo.args
            and isinstance(nodo.args[0], ast.Name)
            and nodo.args[0].id in MODELOS
        ):
            return nodo.args[0].id
        nodo = nodo.func if isinstance(nodo, ast.Call) else nodo.value
    return None


def _escrituras_masivas(arbol):
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        func = nodo.func
        # query(Modelo)....update(...) / .delete(...)
        if isinstance(func, ast.Attribute) and func.attr in ("update", "delete"):
            modelo = _query_de_modelo(func.value)
            if modelo:
                yield nodo.lineno, f"query({modelo}).{func.attr}()"
        # update(Modelo) / delete(Modelo) / insert(Modelo) de SQLAlchemy Core
        if (
            isinstance(func, ast.Name)
            and func.id in ("update", "delete", "insert")
            and nodo.args
            and isinstance(nodo.args[0], ast.Name)
            and nodo.args[0].id in MODELOS
        ):
            yield nodo.lineno, f"{func.id}({nodo.args[0].id})"


def test_nadie_escribe_en_masa_las_tablas_del_plano_de_control():
    hallazgos = []
    for relativa, fuente in _ficheros():
        for linea, que in _escrituras_masivas(ast.parse(fuente)):
            hallazgos.append(f"app/{relativa}:{linea}  {que}")
    assert hallazgos == [], (
        "Escritura sin ORM sobre una tabla del plano de control; no emitiría "
        "eventos:\n" + "\n".join(hallazgos)
    )


def test_nadie_escribe_con_sql_crudo_las_tablas_del_plano_de_control():
    hallazgos = []
    for relativa, fuente in _ficheros():
        for nodo in ast.walk(ast.parse(fuente)):
            if (
                isinstance(nodo, ast.Constant)
                and isinstance(nodo.value, str)
                and SQL_QUE_ESCRIBE.search(nodo.value)
            ):
                hallazgos.append(f"app/{relativa}:{nodo.lineno}")
    assert hallazgos == [], (
        "SQL crudo que escribe una tabla del plano de control; no emitiría "
        "eventos:\n" + "\n".join(hallazgos)
    )


def test_el_detector_ve_lo_que_dice_ver():
    """Sin esto, los dos de arriba podrían pasar porque no detectan nada."""
    fuente = """
db.query(OrganizationUser).filter(x).update({"status": "INACTIVE"})
db.query(UserUnit).filter(y).delete()
session.execute(update(User).values(status="INACTIVE"))
db.query(Plan).filter(z).update({"a": 1})
"""
    encontrados = [que for _, que in _escrituras_masivas(ast.parse(fuente))]
    assert encontrados == [
        "query(OrganizationUser).update()",
        "query(UserUnit).delete()",
        "update(User)",
    ]
    assert SQL_QUE_ESCRIBE.search("UPDATE public.organization_users SET status = 'X'")
    assert SQL_QUE_ESCRIBE.search("delete from user_units where unit_id = :u")
    assert not SQL_QUE_ESCRIBE.search("SELECT user_id FROM public.user_units")

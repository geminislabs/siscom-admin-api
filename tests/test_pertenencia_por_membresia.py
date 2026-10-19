"""Nadie decide pertenencia ni permisos con las dos columnas heredadas.

Antes del selector de cuenta, «pertenecer a una organización» era
`users.organization_id` (hoy `default_organization_id`) y «verla entera» era
`users.is_master`. Las dos son del usuario, no de la membresía, y las dos
dejaron restos que nadie veía:

- `is_master` se leía en quince sitios cuando #174 lo reemplazó por
  `User.is_owner_of`; la docstring de `subject_for_user` decía ser el único.
- `default_organization_id` se comparaba en siete sitios para decidir quién es
  miembro: la lista de usuarios y las concesiones de unidades no veían a quien
  llegó desde otra organización.

La autoridad es la membresía: `access_control.es_miembro` para pertenencia y
`User.is_owner_of` / `is_active_organization_owner` para el rol. Este test
falla si aparece otra comparación con `default_organization_id` o otra lectura
de `.is_master` fuera de las excepciones de abajo, cada una con su razón.

No atrapa todo —SQL crudo u otro nombre no los ve—, pero sí el error más
probable: repetir el patrón que ya existía.
"""

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CARPETAS = ("app/api", "app/services")

# (fichero, función) → por qué ahí sí está bien.
COMPARAR_ORGANIZACION_POR_DEFECTO = {
    (
        "app/api/v1/endpoints/auth.py",
        "list_my_organizations",
    ): "marca cuál es la organización por defecto, que es justo lo que pregunta",
    (
        "app/services/organization.py",
        "reparar_organizacion_por_defecto",
    ): "mantiene el invariante de que la organización por defecto sea una membresía activa",
    (
        "app/api/v1/endpoints/internal/users.py",
        "_es_huerfano",
    ): "mantenimiento de GAC: filas cuya organización de origen ya no existe",
    (
        "app/api/v1/endpoints/internal/users.py",
        "list_internal_users",
    ): "mantenimiento de GAC: filtra la tabla users por su columna, junto a orphaned",
}

LEER_IS_MASTER = {
    (
        "app/api/v1/endpoints/auth.py",
        "resend_verification",
    ): "distingue quien se registró solo (tiene contraseña temporal), no autoriza",
    (
        "app/api/v1/endpoints/auth.py",
        "verify_email",
    ): "distingue quien se registró solo del invitado al verificar el correo, no autoriza",
    (
        "app/api/v1/endpoints/internal/users.py",
        "list_internal_users",
    ): "GAC muestra el valor de la columna",
    (
        "app/api/v1/endpoints/internal/organizations.py",
        "get_organization_users",
    ): "GAC muestra el valor de la columna",
}


def _funciones(arbol):
    """Cada nodo con el nombre de la función que lo contiene."""
    pila = [(arbol, None)]
    while pila:
        nodo, funcion = pila.pop()
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcion = nodo.name
        yield nodo, funcion
        pila.extend((hijo, funcion) for hijo in ast.iter_child_nodes(nodo))


def _es_atributo(nodo, nombre):
    return isinstance(nodo, ast.Attribute) and nodo.attr == nombre


def _hallazgos(predicado):
    for carpeta in CARPETAS:
        for ruta in sorted((RAIZ / carpeta).rglob("*.py")):
            relativa = ruta.relative_to(RAIZ).as_posix()
            arbol = ast.parse(ruta.read_text(encoding="utf-8"))
            for nodo, funcion in _funciones(arbol):
                if predicado(nodo):
                    yield relativa, funcion, nodo.lineno


def _compara_organizacion_por_defecto(nodo):
    return isinstance(nodo, ast.Compare) and any(
        _es_atributo(lado, "default_organization_id")
        for lado in [nodo.left, *nodo.comparators]
    )


def _lee_is_master(nodo):
    return _es_atributo(nodo, "is_master") and isinstance(nodo.ctx, ast.Load)


def _fuera_de(excepciones, hallazgos):
    return [
        f"{fichero}:{linea} (en {funcion})"
        for fichero, funcion, linea in hallazgos
        if (fichero, funcion) not in excepciones
    ]


def test_nadie_decide_pertenencia_por_la_organizacion_por_defecto():
    fuera = _fuera_de(
        COMPARAR_ORGANIZACION_POR_DEFECTO, _hallazgos(_compara_organizacion_por_defecto)
    )
    assert fuera == [], (
        "Comparan default_organization_id; para saber si alguien pertenece a "
        "una organización usa access_control.es_miembro:\n" + "\n".join(fuera)
    )


def test_nadie_autoriza_con_is_master():
    fuera = _fuera_de(LEER_IS_MASTER, _hallazgos(_lee_is_master))
    assert fuera == [], (
        "Leen is_master; para saber si alguien ve o gestiona la organización "
        "usa User.is_active_organization_owner / is_owner_of:\n" + "\n".join(fuera)
    )


def test_las_excepciones_siguen_existiendo():
    """Una excepción cuyo sitio ya no compara ni lee la columna sobra, y una
    lista que solo crece deja de decir algo."""
    usados = set()
    for fichero, funcion, _ in _hallazgos(_compara_organizacion_por_defecto):
        usados.add(("org", fichero, funcion))
    for fichero, funcion, _ in _hallazgos(_lee_is_master):
        usados.add(("master", fichero, funcion))

    sobran = [
        f"default_organization_id: {k}"
        for k in COMPARAR_ORGANIZACION_POR_DEFECTO
        if ("org", *k) not in usados
    ] + [f"is_master: {k}" for k in LEER_IS_MASTER if ("master", *k) not in usados]
    assert sobran == [], "Excepciones que ya no hacen falta:\n" + "\n".join(sobran)


def test_el_detector_ve_lo_que_dice_ver():
    """Sin esto, los de arriba podrían pasar porque no detectan nada."""
    fuente = """
def f(db, current_user, user):
    db.query(User).filter(User.default_organization_id == current_user.organization_id)
    if user.is_master:
        pass
    user.is_master = False
"""
    nodos = [n for n, _ in _funciones(ast.parse(fuente))]
    assert sum(map(_compara_organizacion_por_defecto, nodos)) == 1
    # La lectura cuenta; la asignación no.
    assert sum(map(_lee_is_master, nodos)) == 1

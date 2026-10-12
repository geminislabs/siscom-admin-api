"""La derivación del tema de marca (`app/services/marca_tema.py`).

Lo que importa no es el color exacto de cada paso, sino las garantías: que el
contraste se mide como dice WCAG, que la rampa va de claro a oscuro, que la
semilla se respeta cuando ya cumple y que **ninguna** semilla produce un par
que no pase AA. Esa última se prueba con un barrido, no con tres ejemplos.
"""

import random

import pytest

from app.services import marca_tema as mt


def test_el_contraste_es_el_de_wcag():
    assert mt.contraste("#ffffff", "#000000") == pytest.approx(21.0)
    assert mt.contraste("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)
    # Es simétrico.
    assert mt.contraste("#2563eb", "#ffffff") == mt.contraste("#ffffff", "#2563eb")


def test_la_rampa_va_de_claro_a_oscuro():
    pasos = mt.rampa("#2563eb")
    assert list(pasos) == list(mt.PASOS)
    luminancias = [mt.luminancia(c) for c in pasos.values()]
    assert luminancias == sorted(luminancias, reverse=True)
    assert all(mt.es_hex(c) for c in pasos.values())


def test_una_semilla_que_cumple_se_usa_tal_cual():
    tema = mt.derivar("#2563eb")
    assert tema.tokens["light"]["--color-brand-primary"] == "#2563eb"
    assert tema.tokens["dark"]["--color-brand-primary"] == "#2563eb"
    assert tema.ajustes == []


def test_una_semilla_clara_se_oscurece_en_modo_claro_y_lo_dice():
    """Un amarillo claro sobre blanco es un botón invisible."""
    tema = mt.derivar("#ffeb3b")
    claro = tema.tokens["light"]["--color-brand-primary"]
    assert claro != "#ffeb3b"
    assert min(mt.contraste(claro, f) for f in mt.FONDOS["light"]) >= 3.0
    # En oscuro sí contrasta, así que se respeta.
    assert tema.tokens["dark"]["--color-brand-primary"] == "#ffeb3b"
    assert tema.ajustes == [
        {
            "modo": "light",
            "token": "--color-brand-primary",
            "semilla": "#ffeb3b",
            "usado": claro,
            "motivo": "no contrasta 3.0:1 con el fondo",
        }
    ]


def test_un_azul_marino_se_aclara_en_modo_oscuro():
    tema = mt.derivar("#0a1f44")
    assert tema.tokens["light"]["--color-brand-primary"] == "#0a1f44"
    oscuro = tema.tokens["dark"]["--color-brand-primary"]
    assert min(mt.contraste(oscuro, f) for f in mt.FONDOS["dark"]) >= 3.0


def test_el_acento_propio_se_informa_aparte():
    tema = mt.derivar("#2563eb", "#ffeb3b")
    assert [(a["modo"], a["token"]) for a in tema.ajustes] == [
        ("light", "--color-brand-accent")
    ]


def test_cada_modo_trae_los_mismos_tokens():
    tema = mt.derivar("#00a6c0")
    claves = set(tema.tokens["light"])
    assert claves == set(tema.tokens["dark"])
    assert {
        "--color-brand-primary",
        "--color-brand-on-primary",
        "--color-brand-accent",
        "--color-brand-on-accent",
        "--color-brand-link",
        "--color-brand-50",
        "--color-brand-950",
    } <= claves


@pytest.mark.parametrize(
    "semilla", ["#ffffff", "#000000", "#777777", "#ff0000", "#ffeb3b", "#0a1f44"]
)
def test_los_extremos_pasan_aa(semilla):
    assert mt.derivar(semilla).fallos == []


def test_ninguna_semilla_produce_un_par_que_no_pase_aa():
    """El barrido: 2 000 pares de semillas al azar, con semilla fija."""
    azar = random.Random(20261012)
    for _ in range(2000):
        primario = f"#{azar.randrange(0x1000000):06x}"
        acento = f"#{azar.randrange(0x1000000):06x}"
        fallos = mt.derivar(primario, acento).fallos
        assert fallos == [], (primario, acento, [p.como_dict() for p in fallos])

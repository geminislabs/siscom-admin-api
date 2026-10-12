"""
El tema de una marca: de uno o dos colores semilla a los tokens CSS (B4).

El partner elige su color primario (y, si quiere, uno de acento). El servidor
deriva aquí todo lo demás y lo guarda en `tenant_branding.draft.tokens`. Los
clientes nunca derivan nada: leen tokens ya calculados. Así la web, los
correos y los móviles no tienen que implementar el mismo algoritmo y coincidir
al decimal, y el servidor es la única autoridad sobre qué pasa AA.

POR QUÉ OKLCH
=============
En OKLCH la luminosidad (L) es perceptual: dos colores con la misma L se ven
igual de claros aunque tengan distinto tono. Eso permite construir una rampa
50…950 con la misma progresión de claridad para cualquier color —la misma
idea que la paleta de Tailwind 4, que también está definida en OKLCH—. En HSL,
un amarillo y un azul con la misma «lightness» no se parecen en nada.

QUÉ GARANTIZA
=============
Que cada par de texto/fondo que los clientes van a pintar pase WCAG 2.x:

  - texto sobre el color de marca (botones): 4.5:1 (1.4.3, texto normal);
  - enlaces de marca sobre los fondos de página: 4.5:1;
  - el color de marca contra los fondos de página: 3:1 (1.4.11, componentes
    de interfaz), para que un botón no desaparezca: un amarillo claro sobre
    blanco, o un azul marino sobre el fondo oscuro.

El color de marca se respeta tal cual cuando ya cumple. Si no cumple en un
modo, se usa el paso de su propia rampa más cercano que sí cumpla, y la
respuesta lo dice en `ajustes`. Rechazar el azul marino de un partner porque
en modo oscuro no contrasta sería inútil; moverlo sin decirlo, opaco.

LOS FONDOS DE PÁGINA
====================
Son los de `nexus-web-page` hoy (`src/app.css`): blanco, slate-50 y slate-100
en claro; #020617, #080d1a y slate-900 en oscuro. Si la web cambia sus
superficies, esta lista cambia con ella.
"""

import math
import re
from dataclasses import dataclass, field

# ── Constantes ──────────────────────────────────────────────────────────

FONDOS = {
    "light": ("#ffffff", "#f8fafc", "#f1f5f9"),
    "dark": ("#020617", "#080d1a", "#0f172a"),
}

AA_TEXTO = 4.5
AA_COMPONENTE = 3.0

# Luminosidad OKLCH de cada paso de la rampa. Es la progresión de la paleta
# de Tailwind 4 (aprox.), para que `brand-500` se sienta como `blue-500`.
PASOS = {
    50: 0.971,
    100: 0.936,
    200: 0.885,
    300: 0.808,
    400: 0.704,
    500: 0.637,
    600: 0.577,
    700: 0.505,
    800: 0.444,
    900: 0.396,
    950: 0.258,
}

# Cuánto croma conserva cada paso respecto a la semilla: los extremos casi
# blancos o casi negros no admiten saturación sin salirse de sRGB.
_CROMA_RELATIVO = {
    50: 0.12,
    100: 0.25,
    200: 0.45,
    300: 0.7,
    400: 0.9,
    500: 1.0,
    600: 1.0,
    700: 0.9,
    800: 0.75,
    900: 0.6,
    950: 0.45,
}

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# ── Conversión de color ─────────────────────────────────────────────────


def es_hex(valor: str) -> bool:
    return bool(_HEX_RE.match(valor or ""))


def _hex_a_rgb(hex_: str) -> tuple[float, float, float]:
    h = hex_.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_a_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(min(1.0, max(0.0, c)) * 255):02x}" for c in rgb)


def _a_lineal(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _de_lineal(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _rgb_a_oklch(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (_a_lineal(c) for c in rgb)
    l_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m_ = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l_, m_, s_))
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    C = math.hypot(a, bb)
    H = math.degrees(math.atan2(bb, a)) % 360
    return L, C, H


def _oklch_a_rgb_lineal(L: float, C: float, H: float) -> tuple[float, float, float]:
    a = C * math.cos(math.radians(H))
    b = C * math.sin(math.radians(H))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )


def _oklch_a_hex(L: float, C: float, H: float) -> str:
    """Al hex más cercano dentro de sRGB, bajando croma si hace falta.

    Bajar croma conserva la claridad y el tono, que es lo que el ojo nota; un
    recorte por canal los cambiaría.
    """
    bajo, alto = 0.0, C
    lineal = _oklch_a_rgb_lineal(L, C, H)
    if all(-1e-6 <= c <= 1 + 1e-6 for c in lineal):
        return _rgb_a_hex(tuple(_de_lineal(max(0.0, c)) for c in lineal))
    for _ in range(24):
        medio = (bajo + alto) / 2
        lineal = _oklch_a_rgb_lineal(L, medio, H)
        if all(-1e-6 <= c <= 1 + 1e-6 for c in lineal):
            bajo = medio
        else:
            alto = medio
    lineal = _oklch_a_rgb_lineal(L, bajo, H)
    return _rgb_a_hex(tuple(_de_lineal(min(1.0, max(0.0, c))) for c in lineal))


# ── Contraste WCAG ──────────────────────────────────────────────────────


def luminancia(hex_: str) -> float:
    r, g, b = (_a_lineal(c) for c in _hex_a_rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ── Derivación ──────────────────────────────────────────────────────────


def rampa(semilla: str) -> dict[int, str]:
    """Los once pasos 50…950 con el tono de la semilla."""
    _, C, H = _rgb_a_oklch(_hex_a_rgb(semilla))
    return {
        paso: _oklch_a_hex(L, C * _CROMA_RELATIVO[paso], H) for paso, L in PASOS.items()
    }


def _peor_contraste(color: str, fondos: tuple[str, ...]) -> float:
    return min(contraste(color, f) for f in fondos)


def _mas_cercano_que_cumpla(
    semilla: str, candidatos: dict[int, str], fondos: tuple[str, ...], minimo: float
) -> str | None:
    """La semilla si cumple; si no, el paso que cumple con la L más parecida."""
    if _peor_contraste(semilla, fondos) >= minimo:
        return semilla
    L_semilla = _rgb_a_oklch(_hex_a_rgb(semilla))[0]
    validos = [
        (abs(PASOS[p] - L_semilla), c)
        for p, c in candidatos.items()
        if _peor_contraste(c, fondos) >= minimo
    ]
    return min(validos)[1] if validos else None


def _texto_sobre(fondo: str, rampa_: dict[int, str]) -> str:
    """Blanco, o el paso más oscuro de la rampa, o negro: el primero que pase."""
    for candidato in ("#ffffff", rampa_[950], "#000000"):
        if contraste(candidato, fondo) >= AA_TEXTO:
            return candidato
    # Entre blanco y negro siempre hay uno por encima de 4.5:1 —el peor caso
    # ronda 4.58:1—, así que esto no ocurre; si ocurre, lo atrapa la
    # validación final y sale un 422 en vez de un tema ilegible.
    return "#000000"


@dataclass
class Par:
    """Un par texto/fondo comprobado, tal como se informa al cliente."""

    modo: str
    nombre: str
    primero: str
    segundo: str
    ratio: float
    minimo: float

    @property
    def cumple(self) -> bool:
        return self.ratio >= self.minimo

    def como_dict(self) -> dict:
        return {
            "modo": self.modo,
            "par": self.nombre,
            "colores": [self.primero, self.segundo],
            "ratio": round(self.ratio, 2),
            "minimo": self.minimo,
        }


@dataclass
class Tema:
    tokens: dict[str, dict[str, str]]
    pares: list[Par] = field(default_factory=list)
    ajustes: list[dict] = field(default_factory=list)

    @property
    def fallos(self) -> list[Par]:
        return [p for p in self.pares if not p.cumple]


def derivar(primario: str, acento: str | None = None) -> Tema:
    """
    Los tokens de los dos modos a partir de las semillas.

    Devuelve también cada par comprobado y los ajustes hechos a las semillas.
    Quien llama decide qué hacer con `fallos`; el endpoint responde 422.
    """
    acento_propio = acento is not None
    acento = acento or primario
    rampa_marca = rampa(primario)
    rampa_acento = rampa(acento)

    tokens: dict[str, dict[str, str]] = {}
    pares: list[Par] = []
    ajustes: list[dict] = []

    for modo, fondos in FONDOS.items():
        mapa = {f"--color-brand-{p}": c for p, c in rampa_marca.items()}

        for rol, semilla, rampa_ in (
            ("primary", primario, rampa_marca),
            ("accent", acento, rampa_acento),
        ):
            color = (
                _mas_cercano_que_cumpla(semilla, rampa_, fondos, AA_COMPONENTE)
                or semilla
            )
            # Sin acento propio, el acento es el primario: su ajuste ya se
            # informó una vez y repetirlo solo confunde.
            if color != semilla and (rol == "primary" or acento_propio):
                ajustes.append(
                    {
                        "modo": modo,
                        "token": f"--color-brand-{rol}",
                        "semilla": semilla,
                        "usado": color,
                        "motivo": f"no contrasta {AA_COMPONENTE}:1 con el fondo",
                    }
                )
            sobre = _texto_sobre(color, rampa_)
            mapa[f"--color-brand-{rol}"] = color
            mapa[f"--color-brand-on-{rol}"] = sobre

            pares.append(
                Par(
                    modo,
                    f"on-{rol}/{rol}",
                    sobre,
                    color,
                    contraste(sobre, color),
                    AA_TEXTO,
                )
            )
            for fondo in fondos:
                pares.append(
                    Par(
                        modo,
                        f"{rol}/fondo",
                        color,
                        fondo,
                        contraste(color, fondo),
                        AA_COMPONENTE,
                    )
                )

        enlace = (
            _mas_cercano_que_cumpla(primario, rampa_marca, fondos, AA_TEXTO) or primario
        )
        mapa["--color-brand-link"] = enlace
        for fondo in fondos:
            pares.append(
                Par(
                    modo,
                    "link/fondo",
                    enlace,
                    fondo,
                    contraste(enlace, fondo),
                    AA_TEXTO,
                )
            )

        tokens[modo] = mapa

    return Tema(tokens=tokens, pares=pares, ajustes=ajustes)

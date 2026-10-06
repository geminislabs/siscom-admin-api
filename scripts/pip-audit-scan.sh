#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null

# PYSEC-2026-1325 — ecdsa (transitivo vía python-jose): Minerva, ataque de timing
# sobre P-256. Sin versión corregida; los maintainers consideran los ataques de canal
# lateral fuera de alcance del proyecto. No aplica a este servicio: `app/core/security.py`
# solo hace `jwt.decode` con `algorithms=["RS256"]` — no firmamos, no generamos llaves y
# no usamos ECDH, y la verificación de firmas no está afectada por esta vulnerabilidad.
# Mismo riesgo ya aceptado para OSV en `osv-scanner.toml` y en la alerta de
# Dependabot. El registro con el razonamiento completo y la condicion que lo
# invalidaria vive en `docs/security/threat-model.md`, seccion Riesgos aceptados.
#
# CVE-2026-85394 — python-jose <= 3.5.0: acepta una llave pública RSA en DER como
# secreto HMAC, así que con la llave pública se puede forjar un HS256 si
# `jwt.decode` no restringe algoritmos. Sin versión corregida. No aplica a este
# servicio por dos barreras: `algorithms=["RS256"]` en las dos llamadas, y la
# llave llega de las JWKS como JWK, no como bytes. Lo prueba el ataque mismo en
# `tests/test_confusion_de_algoritmo.py`. OSV la reporta como GHSA-3qf3-8w2g-rqmx y
# está silenciada en `osv-scanner.toml` con el mismo razonamiento. Registro completo en
# `docs/security/threat-model.md`, sección Riesgos aceptados.
exec pip-audit -r requirements.txt --desc on \
  --ignore-vuln PYSEC-2026-1325 \
  --ignore-vuln CVE-2026-85394

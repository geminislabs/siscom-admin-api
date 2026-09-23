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
# PYSEC-2026-3447 — setuptools 81: el arreglo está en 83, que ya no trae
# pkg_resources. opentelemetry-instrumentation 0.48b0 lo importa al arrancar.
# El fallo es al armar un sdist (MANIFEST.in y Unicode); este servicio no
# publica paquetes.
#
# PYSEC-2026-1805 — protobuf 4.25.9, transitivo de opentelemetry-proto 1.27
# (protobuf<5). El arreglo es 5.29.6 o 6.33.5. El fallo es ParseDict de Any
# anidados; esta API no parsea protobuf JSON de clientes.
exec pip-audit -r requirements.txt --desc on \
  --ignore-vuln PYSEC-2026-1325 \
  --ignore-vuln PYSEC-2026-3447 \
  --ignore-vuln PYSEC-2026-1805

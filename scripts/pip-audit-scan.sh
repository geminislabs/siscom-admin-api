#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null

# Sin excepciones desde el 06/10/2026: las dos que había (PYSEC-2026-1325 de
# `ecdsa` y CVE-2026-85394 de `python-jose`) venían de `python-jose`, que se
# cambió por PyJWT. Si vuelve a hacer falta una, registrarla aquí y en
# `osv-scanner.toml` con su razonamiento, y en `docs/security/threat-model.md`.
exec pip-audit -r requirements.txt --desc on

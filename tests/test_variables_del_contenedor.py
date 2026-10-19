"""Toda variable que el deploy escribe en el `.env` llega al contenedor.

`deploy.yml` escribe un `.env` en el servidor, pero el contenedor de la API no
lo carga entero: `docker-compose.prod.yml` copia al contenedor solo las
variables que nombra en su bloque `environment:`. Una variable que esté en el
`.env` y no en ese bloque no existe para la API, y el código usa su valor por
defecto sin avisar.

Pasó el 19/10/2026 con `KAFKA_CONTROL_PLANE_*`: el deploy las escribía, la API
no las veía, y publicaba en `control-plane-events` con el usuario de Kafka
general, que no tiene ACL sobre ese topic. Cada evento terminaba en
`TopicAuthorizationFailedError` y ningún consumidor recibía nada.
"""

import re
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]

# Solo las usa el `docker run` de alembic del deploy (`--env-file .env`), no la
# API: a propósito no están en el contenedor de runtime.
SOLO_PARA_MIGRAR = {"DB_MIGRATION_USER", "DB_MIGRATION_PASSWORD"}


def _variables_del_env_del_deploy() -> set[str]:
    deploy = (RAIZ / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    # El cierre se busca como línea propia: «EOF» aparece dentro de nombres
    # como GEOFENCES.
    bloque = re.search(r"cat > \.env << EOF\n(.*?)\n\s*EOF\s*\n", deploy, re.S)
    assert bloque, "no encontré el `cat > .env << EOF` de deploy.yml"
    return set(re.findall(r"^\s*([A-Z0-9_]+)=", bloque.group(1), re.M))


def _variables_del_contenedor() -> set[str]:
    compose = yaml.safe_load(
        (RAIZ / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    return set(compose["services"]["siscom-admin-api"]["environment"])


def test_toda_variable_del_env_llega_al_contenedor():
    faltan = _variables_del_env_del_deploy() - _variables_del_contenedor()
    assert faltan == SOLO_PARA_MIGRAR, (
        "Están en el .env del deploy pero no en el environment de "
        f"docker-compose.prod.yml, así que la API no las ve: {sorted(faltan - SOLO_PARA_MIGRAR)}"
    )


def test_el_contenedor_no_pide_variables_que_el_deploy_no_escribe():
    sobran = _variables_del_contenedor() - _variables_del_env_del_deploy()
    assert sobran == set(), (
        "docker-compose.prod.yml las pasa al contenedor, pero el deploy no las "
        f"escribe en el .env: llegarían vacías. {sorted(sobran)}"
    )

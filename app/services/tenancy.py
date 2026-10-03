"""
Resolución de marca por `Host`: de un hostname a la `Account` que lo posee.

Vivía solo dentro de `app/api/v1/endpoints/tenant_config.py` (que la usa para
pintar branding). La rebanada B3 necesita la misma resolución para filtrar
credenciales en `/auth/login` y `/auth/register`, así que se comparte aquí en
vez de duplicarla.

LA REGLA QUE MÁS ERRORES PREVIENE EN ESTAS PLATAFORMAS
======================================================
**El Host resuelve apariencia y NUNCA autoriza.** El tenant de marca y el tenant
de datos son cosas distintas: la marca la determina el dominio por el que entró
la petición; los datos, el subárbol del usuario autenticado. Que alguien mande
`Host: meromero.com` a mano no le da acceso a nada — a lo sumo elige con qué
credencial se intenta entrar, nunca qué se puede ver.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.tenancy import TenantDomain


def normalizar_host(host: str | None) -> str | None:
    """
    Deja el `Host` como está guardado en `tenant_domains`, o `None` si no puede.

    El Host llega en la caja que mande el cliente y puede traer puerto, punto
    final o mayúsculas. La columna es minúsculas por restricción de la base
    justamente para que la búsqueda sea una igualdad indexable.

    Devuelve `None` —y no una cadena vacía ni el valor crudo— cuando el Host no
    sirve: quien llama tiene que decidir explícitamente qué hacer con eso, en
    lugar de acabar consultando por "" y encontrando lo que sea.
    """
    if not host:
        return None
    host = host.strip().lower().rstrip(".")
    # IPv6 entre corchetes: [::1]:8000
    if host.startswith("["):
        cierre = host.find("]")
        if cierre == -1:
            return None
        host = host[: cierre + 1]
    elif ":" in host:
        host = host.split(":", 1)[0]
    if not host or len(host) > 253:
        return None
    return host


def resolver_account_id_de_host(hostname: str | None, db: Session) -> UUID | None:
    """
    La cuenta de marca dueña de `hostname`, o `None` si no hay ninguna.

    `None` significa «marca por defecto» — no es un error, es el suelo que
    describe §26 del documento de arquitectura. Pasa eso mismo: recibe el
    resultado de `normalizar_host`, ya normalizado, para no repetir esa regla
    en cada llamador.

    Solo cuenta un dominio **verificado**: uno en `PENDING` lo puede reclamar
    cualquiera hasta que demuestre control por DNS, y resolver su marca antes
    de eso permitiría suplantar a un partner con solo apuntar un CNAME.
    """
    if hostname is None:
        return None
    dominio = (
        db.query(TenantDomain)
        .filter(
            TenantDomain.hostname == hostname,
            TenantDomain.status == "VERIFIED",
        )
        .first()
    )
    return dominio.account_id if dominio else None


def resolver_dominio_publico_de_account(account_id: UUID, db: Session) -> str | None:
    """
    El hostname primario y verificado de una cuenta de marca, o `None`.

    Es la inversa de `resolver_account_id_de_host`: de cuenta a dominio en vez
    de dominio a cuenta. La usa B4 (plantillas de SES por marca) para construir
    el enlace de acción de un correo — si la marca no tiene un dominio propio
    verificado, el llamador cae a `settings.FRONTEND_URL`, mismo criterio de
    "marca por defecto nunca es error" que el resto de esta rebanada.
    """
    dominio = (
        db.query(TenantDomain)
        .filter(
            TenantDomain.account_id == account_id,
            TenantDomain.status == "VERIFIED",
            TenantDomain.is_primary.is_(True),
        )
        .first()
    )
    return dominio.hostname if dominio else None

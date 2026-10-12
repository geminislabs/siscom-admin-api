"""
Resolución de permisos por rol (D6 de B4).

Punto único para decidir si un rol tiene un permiso del catálogo. Los
endpoints no preguntan por nombre de rol sino por permiso, a través de
`require_account_permission` (`app/api/deps.py`); la sesión (`GET /auth/me`)
expone los mismos permisos para que el menú de los clientes se derive de aquí
y nunca los sustituya.

HOY Y MAÑANA
============
Hoy los roles son los cuatro de sistema, y las membresías guardan su código
como texto (`account_users.role`). Por eso la búsqueda es por
`(alcance, código)` entre los roles de sistema. Con los roles personalizados la
membresía apuntará a un `role_id` y la búsqueda cambiará aquí, en un solo
sitio; los endpoints no se enteran.

FALLA CERRADO
=============
Un rol que no existe, un permiso que el catálogo no tiene o una membresía sin
rol dan «sin permiso», nunca un error ni un permiso por defecto. Que la
migración 038 no haya corrido produce 403, no acceso.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models.permission import Role, RolePermission


def permisos_de_rol(db: Session, scope: str, role_code: Optional[str]) -> set[str]:
    """Los códigos de permiso del rol de sistema `(scope, role_code)`."""
    if not role_code:
        return set()

    filas = (
        db.query(RolePermission.permission_code)
        .join(Role, Role.id == RolePermission.role_id)
        .filter(
            Role.scope == scope,
            Role.code == role_code,
            Role.account_id.is_(None),
            RolePermission.scope == scope,
        )
        .all()
    )
    return {code for (code,) in filas}


def tiene_permiso(
    db: Session, scope: str, role_code: Optional[str], permission: str
) -> bool:
    """Si el rol de sistema `(scope, role_code)` tiene `permission`."""
    return permission in permisos_de_rol(db, scope, role_code)

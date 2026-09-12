"""
Dependencias de Autenticación y Autorización.

Este módulo proporciona dependencias de FastAPI para:
- Autenticación con Cognito (API pública)
- Autenticación con PASETO (API interna)
- Autorización basada en roles organizacionales
- Resolución de capabilities

MODELO CONCEPTUAL:
==================
Account = Raíz comercial (billing, facturación)
Organization = Raíz operativa (permisos, uso diario)

Los usuarios pertenecen a Organizations.
Las dependencias resuelven organization_id para validar permisos.

IMPORTANTE: La resolución de roles SIEMPRE usa OrganizationService.get_user_role()
como única fuente de verdad. El campo is_master es un fallback legacy manejado
internamente por OrganizationService.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import verify_cognito_token
from app.db.session import get_db
from app.services.messaging.kafka_producer import (
    GeofencesKafkaProducer,
    MobilityKafkaProducer,
    RulesKafkaProducer,
    TeamRulesKafkaProducer,
    UnitDevicesKafkaProducer,
    UserDevicesKafkaProducer,
    UserUnitsKafkaProducer,
)
from app.services.organization import OrganizationService
from app.utils.paseto_token import decode_service_token

if TYPE_CHECKING:  # pragma: no cover - solo para anotaciones
    from app.services.identity import IdentityProvider
    from app.services.scope_store import ScopeStore
    from app.utils.data_token import DataTokenIssuer


class BearerAuth(HTTPBearer):
    """
    `HTTPBearer` que responde 401 en lugar del 403 por defecto de FastAPI.

    FastAPI lanza `403 Not authenticated` cuando falta el header `Authorization`
    o cuando el esquema no es Bearer, lo que invierte la semántica de HTTP: el 401
    es "no sé quién eres, autentícate" y el 403 es "sé quién eres y aun así no
    puedes". Con el 403 el servicio respondía algo *más* restrictivo ante la
    ausencia de credenciales que ante credenciales inválidas (que sí dan 401).

    Además dejaba a los clientes sin señal accionable: tanto iOS como Android
    disparan el refresh de token únicamente con un 401, así que una petición sin
    header terminaba en un error genérico del que la app no se recuperaba sola.

    Se preserva el `detail` original y se agrega el `WWW-Authenticate` que exige
    RFC 9110 para las respuestas 401.
    """

    async def __call__(  # type: ignore[override]
        self, request: Request
    ) -> Optional[HTTPAuthorizationCredentials]:
        try:
            return await super().__call__(request)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=exc.detail,
                    headers={"WWW-Authenticate": "Bearer"},
                ) from exc
            raise


security = BearerAuth()
_rules_kafka_producer: Optional[RulesKafkaProducer] = None
_geofences_kafka_producer: Optional[GeofencesKafkaProducer] = None
_user_devices_kafka_producer: Optional[UserDevicesKafkaProducer] = None
_unit_devices_kafka_producer: Optional[UnitDevicesKafkaProducer] = None
_user_units_kafka_producer: Optional[UserUnitsKafkaProducer] = None
_mobility_kafka_producer: Optional[MobilityKafkaProducer] = None
_team_rules_kafka_producer: Optional[TeamRulesKafkaProducer] = None


def get_rules_kafka_producer() -> RulesKafkaProducer:
    """Retorna una instancia singleton del producer de reglas."""
    global _rules_kafka_producer
    if _rules_kafka_producer is None:
        _rules_kafka_producer = RulesKafkaProducer()
    return _rules_kafka_producer


def get_user_devices_kafka_producer() -> UserDevicesKafkaProducer:
    """Retorna una instancia singleton del producer de user devices."""
    global _user_devices_kafka_producer
    if _user_devices_kafka_producer is None:
        _user_devices_kafka_producer = UserDevicesKafkaProducer()
    return _user_devices_kafka_producer


def get_unit_devices_kafka_producer() -> UnitDevicesKafkaProducer:
    """Retorna una instancia singleton del producer de asignaciones unit-device."""
    global _unit_devices_kafka_producer
    if _unit_devices_kafka_producer is None:
        _unit_devices_kafka_producer = UnitDevicesKafkaProducer()
    return _unit_devices_kafka_producer


def get_user_units_kafka_producer() -> UserUnitsKafkaProducer:
    """Retorna una instancia singleton del producer de user_units."""
    global _user_units_kafka_producer
    if _user_units_kafka_producer is None:
        _user_units_kafka_producer = UserUnitsKafkaProducer()
    return _user_units_kafka_producer


def get_geofences_kafka_producer() -> GeofencesKafkaProducer:
    """Retorna una instancia singleton del producer de geocercas."""
    global _geofences_kafka_producer
    if _geofences_kafka_producer is None:
        _geofences_kafka_producer = GeofencesKafkaProducer()
    return _geofences_kafka_producer


def get_mobility_kafka_producer() -> MobilityKafkaProducer:
    """Retorna una instancia singleton del producer de mobility."""
    global _mobility_kafka_producer
    if _mobility_kafka_producer is None:
        _mobility_kafka_producer = MobilityKafkaProducer()
    return _mobility_kafka_producer


def get_team_rules_kafka_producer() -> TeamRulesKafkaProducer:
    """Retorna una instancia singleton del producer de team rules."""
    global _team_rules_kafka_producer
    if _team_rules_kafka_producer is None:
        _team_rules_kafka_producer = TeamRulesKafkaProducer()
    return _team_rules_kafka_producer


_data_token_issuer: Optional["DataTokenIssuer"] = None
_scope_store: Optional["ScopeStore"] = None


def get_data_token_issuer() -> "DataTokenIssuer":
    """Emisor de data tokens (singleton: la clave se carga una vez)."""
    global _data_token_issuer
    if _data_token_issuer is None:
        from app.utils.data_token import DataTokenIssuer

        _data_token_issuer = DataTokenIssuer()
    return _data_token_issuer


def get_scope_store() -> "ScopeStore":
    """Store de alcances en Valkey (singleton: reutiliza el pool de conexiones)."""
    global _scope_store
    if _scope_store is None:
        from app.services.scope_store import ScopeStore, build_client

        _scope_store = ScopeStore(build_client())
    return _scope_store


def get_identity_provider() -> "IdentityProvider":
    """El proveedor de identidad del despliegue.

    Es una dependencia y no un import directo para que una prueba pueda
    sustituirlo con `dependency_overrides` sin parchear módulos. Los endpoints
    que ya conocen la marca de la petición —rebanada B3— usarán en su lugar
    `proveedor_para_cuenta()`, que es quien de verdad enruta.
    """
    from app.services.identity import proveedor_por_defecto

    return proveedor_por_defecto()


def close_rules_kafka_producer() -> None:
    global _rules_kafka_producer
    if _rules_kafka_producer is not None:
        _rules_kafka_producer.close()
        _rules_kafka_producer = None


def close_user_devices_kafka_producer() -> None:
    global _user_devices_kafka_producer
    if _user_devices_kafka_producer is not None:
        _user_devices_kafka_producer.close()
        _user_devices_kafka_producer = None


def close_unit_devices_kafka_producer() -> None:
    global _unit_devices_kafka_producer
    if _unit_devices_kafka_producer is not None:
        _unit_devices_kafka_producer.close()
        _unit_devices_kafka_producer = None


def close_user_units_kafka_producer() -> None:
    global _user_units_kafka_producer
    if _user_units_kafka_producer is not None:
        _user_units_kafka_producer.close()
        _user_units_kafka_producer = None


def close_geofences_kafka_producer() -> None:
    global _geofences_kafka_producer
    if _geofences_kafka_producer is not None:
        _geofences_kafka_producer.close()
        _geofences_kafka_producer = None


def close_mobility_kafka_producer() -> None:
    global _mobility_kafka_producer
    if _mobility_kafka_producer is not None:
        _mobility_kafka_producer.close()
        _mobility_kafka_producer = None


def close_team_rules_kafka_producer() -> None:
    global _team_rules_kafka_producer
    if _team_rules_kafka_producer is not None:
        _team_rules_kafka_producer.close()
        _team_rules_kafka_producer = None


@dataclass
class AuthResult:
    """
    Resultado de autenticación que soporta tanto Cognito como PASETO.

    Attributes:
        auth_type: Tipo de autenticación ('cognito' o 'paseto')
        payload: Payload del token decodificado
        user_id: ID del usuario (solo Cognito)
        organization_id: ID de la organización (solo Cognito)
        organization_role: Rol del usuario en la organización (solo Cognito)
        service: Nombre del servicio (solo PASETO)
        role: Rol del servicio (solo PASETO)
    """

    auth_type: Literal["cognito", "paseto"]
    payload: dict
    # Solo para Cognito
    user_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    organization_role: Optional[str] = None
    # Solo para PASETO service tokens
    service: Optional[str] = None
    role: Optional[str] = None

    # Alias de compatibilidad (DEPRECATED)
    @property
    def client_id(self) -> Optional[UUID]:
        """DEPRECATED: Usar organization_id"""
        return self.organization_id


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Extrae y valida el token de Cognito del header Authorization.
    Retorna el payload del token validado.
    """
    token = credentials.credentials
    payload = verify_cognito_token(token)
    return payload


def resolve_current_organization(db: Session, cognito_payload: dict) -> UUID:
    """
    Busca el usuario por cognito_sub y retorna su organization_id.
    """
    from app.models.user import User

    cognito_sub = cognito_payload.get("sub")
    if not cognito_sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido: falta 'sub'",
        )

    user = db.query(User).filter(User.cognito_sub == cognito_sub).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en el sistema",
        )

    return user.organization_id


# Alias de compatibilidad (DEPRECATED)
def resolve_current_client(db: Session, cognito_payload: dict) -> UUID:
    """DEPRECATED: Usar resolve_current_organization"""
    return resolve_current_organization(db, cognito_payload)


def get_current_organization_id(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> UUID:
    """
    Dependency que combina autenticación y resolución de organization_id.
    Retorna el organization_id del usuario autenticado.
    """
    return resolve_current_organization(db, current_user)


# Alias de compatibilidad (DEPRECATED)
def get_current_client_id(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> UUID:
    """DEPRECATED: Usar get_current_organization_id"""
    return get_current_organization_id(db, current_user)


def get_current_user_full(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retorna el objeto User completo del usuario autenticado.
    """
    from app.models.user import User

    cognito_sub = current_user.get("sub")
    user = db.query(User).filter(User.cognito_sub == cognito_sub).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )

    return user


def get_current_user_id(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> UUID:
    """
    Retorna el UUID del usuario autenticado.
    """
    from app.models.user import User

    cognito_sub = current_user.get("sub")
    user = db.query(User).filter(User.cognito_sub == cognito_sub).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )

    return user.id


def get_current_user_with_role(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> tuple:
    """
    Retorna el usuario y su rol organizacional.

    DELEGACIÓN: Usa OrganizationService.get_user_role() como única fuente
    de verdad para roles. El fallback a is_master se maneja internamente.

    Returns:
        Tuple de (User, OrganizationRole o None)
    """
    from app.models.user import User

    cognito_sub = current_user.get("sub")
    user = db.query(User).filter(User.cognito_sub == cognito_sub).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )

    # Obtener rol usando OrganizationService (única fuente de verdad)
    role = OrganizationService.get_user_role(db, user.id, user.organization_id)

    return user, role


def get_auth_cognito_or_paseto(
    required_service: Optional[str] = None,
    required_role: Optional[str] = None,
):
    """
    Factory para crear una dependencia que acepta tanto Cognito como PASETO.

    Args:
        required_service: Servicio requerido para tokens PASETO (ej: "gac")
        required_role: Rol requerido para tokens PASETO (ej: "GAC_ADMIN")

    Returns:
        Una dependencia de FastAPI que valida el token y retorna AuthResult
    """

    def _verify_auth(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db),
    ) -> AuthResult:
        """
        Verifica el token de autenticación.
        Intenta primero con Cognito, si falla intenta con PASETO.

        DELEGACIÓN: Usa OrganizationService.get_user_role() como única fuente
        de verdad para roles. El fallback a is_master se maneja internamente.
        """
        from app.models.user import User

        token = credentials.credentials

        # Intentar primero con Cognito
        try:
            cognito_payload = verify_cognito_token(token)

            # Si llegamos aquí, es un token de Cognito válido
            cognito_sub = cognito_payload.get("sub")
            if not cognito_sub:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token de Cognito inválido: falta 'sub'",
                )

            user = db.query(User).filter(User.cognito_sub == cognito_sub).first()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Usuario no encontrado en el sistema",
                )

            # Obtener rol usando OrganizationService (única fuente de verdad)
            org_role = OrganizationService.get_user_role(
                db, user.id, user.organization_id
            )
            # Convertir a string para el AuthResult
            org_role_str = org_role.value if org_role else None

            return AuthResult(
                auth_type="cognito",
                payload=cognito_payload,
                user_id=user.id,
                organization_id=user.organization_id,
                organization_role=org_role_str,
            )

        except HTTPException as exc:
            # Solo se cae al camino PASETO cuando el fallo es de CREDENCIAL. Un
            # fallo del lado del servidor —Cognito inalcanzable, sin JWKS ni
            # caché— no puede acabar respondiendo 401: eso le diría al cliente
            # que su credencial es mala y lo mandaría a reautenticarse contra un
            # problema que ninguna credencial arregla. Peor aún, los clientes que
            # reaccionan a un 401 pidiendo un token nuevo convierten una caída de
            # Cognito en una tormenta de peticiones sobre esta misma API.
            if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
                raise
            # 401/403: la credencial no vale para Cognito; puede ser un PASETO.
        except Exception:
            # Cualquier otro error de Cognito, intentar con PASETO
            pass

        # Intentar con PASETO service token
        paseto_payload = decode_service_token(
            token,
            required_service=required_service,
            required_role=required_role,
        )

        if paseto_payload:
            return AuthResult(
                auth_type="paseto",
                payload=paseto_payload,
                service=paseto_payload.get("service"),
                role=paseto_payload.get("role"),
            )

        # Si ambos fallaron, retornar error
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido. Se requiere un token de Cognito válido o un token PASETO de servicio válido.",
        )

    return _verify_auth


def require_organization_role(*allowed_roles: str):
    """
    Factory para crear una dependencia que requiere roles específicos.

    DELEGACIÓN: Usa OrganizationService.get_user_role() como única fuente
    de verdad para roles. El fallback a is_master se maneja internamente.

    JERARQUÍA DE ROLES:
    - owner: Tiene todos los permisos
    - admin: Tiene permisos de admin, billing y member
    - billing: Tiene permisos de billing y member
    - member: Solo permisos de member

    Uso:
        @router.post("/admin-action")
        def admin_action(
            auth: AuthResult = Depends(require_organization_role("owner", "admin"))
        ):
            ...

    Args:
        allowed_roles: Roles mínimos permitidos (ej: "owner", "admin", "billing", "member")

    Returns:
        Dependencia que valida el rol y retorna AuthResult
    """
    # Definir jerarquía de roles (de mayor a menor)
    ROLE_HIERARCHY = {
        "owner": ["owner", "admin", "billing", "member"],
        "admin": ["admin", "billing", "member"],
        "billing": ["billing", "member"],
        "member": ["member"],
    }

    def _require_role(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db),
    ) -> AuthResult:
        from app.models.user import User

        token = credentials.credentials

        # Solo soporta Cognito para verificación de roles organizacionales
        cognito_payload = verify_cognito_token(token)

        cognito_sub = cognito_payload.get("sub")
        if not cognito_sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido: falta 'sub'",
            )

        user = db.query(User).filter(User.cognito_sub == cognito_sub).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado",
            )

        # Obtener rol usando OrganizationService (única fuente de verdad)
        org_role = OrganizationService.get_user_role(db, user.id, user.organization_id)
        org_role_str = org_role.value if org_role else None

        # Validar rol con jerarquía
        # El usuario tiene acceso si su rol incluye alguno de los roles permitidos
        user_permissions = ROLE_HIERARCHY.get(org_role_str, [])
        has_permission = any(role in user_permissions for role in allowed_roles)

        if not has_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere uno de los siguientes roles: {', '.join(allowed_roles)}",
            )

        return AuthResult(
            auth_type="cognito",
            payload=cognito_payload,
            user_id=user.id,
            organization_id=user.organization_id,
            organization_role=org_role_str,
        )

    return _require_role


def require_capability(capability_code: str):
    """
    Factory para crear una dependencia que requiere una capability habilitada.

    Uso:
        @router.post("/ai-analyze")
        def ai_analyze(
            auth: AuthResult = Depends(require_capability("ai_features"))
        ):
            ...

    Args:
        capability_code: Código de la capability requerida

    Returns:
        Dependencia que valida la capability y retorna AuthResult
    """

    def _require_capability(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db),
    ) -> AuthResult:
        from app.models.user import User
        from app.services.capabilities import CapabilityService

        token = credentials.credentials
        cognito_payload = verify_cognito_token(token)

        cognito_sub = cognito_payload.get("sub")
        if not cognito_sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido: falta 'sub'",
            )

        user = db.query(User).filter(User.cognito_sub == cognito_sub).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado",
            )

        # Verificar capability
        if not CapabilityService.has_capability(
            db, user.organization_id, capability_code
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"La organización no tiene acceso a: {capability_code}",
            )

        return AuthResult(
            auth_type="cognito",
            payload=cognito_payload,
            user_id=user.id,
            organization_id=user.organization_id,
        )

    return _require_capability


# Dependencias pre-configuradas
get_auth_for_gac_admin = get_auth_cognito_or_paseto(
    required_service="gac",
    required_role="GAC_ADMIN",
)

# Dependencias de rol comunes
require_owner = require_organization_role("owner")
require_admin_or_owner = require_organization_role("owner", "admin")
require_billing_access = require_organization_role("owner", "billing")

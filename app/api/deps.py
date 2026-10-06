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
como única fuente de verdad, y desde el 22/09/2026 esa función es realmente la
única: el *fallback* a is_master se borró. El rol sale de `organization_users`
y de ningún otro sitio.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
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
    from app.models.account import Account
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


def get_cuenta_de_marca(
    request: Request, db: Session = Depends(get_db)
) -> Optional["Account"]:
    """La `Account` de marca para esta petición, resuelta por `Host`.

    `None` significa «marca por defecto» — el suelo de §26 del documento de
    arquitectura, nunca un error. Hoy es siempre `None` en producción: no hay
    ningún `tenant_domains` verificado todavía, y el `Host` que ve esta API en
    peticiones de `nexus-web-page` es el suyo propio, no el del visitante —
    conectar eso es trabajo de la Fase 4/5, no de esta rebanada (B3).
    """
    from app.models.account import Account
    from app.services.tenancy import normalizar_host, resolver_account_id_de_host

    account_id = resolver_account_id_de_host(
        normalizar_host(request.headers.get("host")), db
    )
    return db.get(Account, account_id) if account_id else None


def get_identity_provider_para_login(
    cuenta: Optional["Account"] = Depends(get_cuenta_de_marca),
) -> "IdentityProvider":
    """El proveedor de identidad de la marca resuelta — rebanada B3.

    Es la dependencia que anticipaba el docstring de `get_identity_provider`:
    ahora que `/auth/login` y `/auth/register` conocen la marca de la
    petición, enrutan con `proveedor_para_cuenta()` en vez del proveedor por
    defecto siempre.
    """
    from app.services.identity import proveedor_para_cuenta

    return proveedor_para_cuenta(cuenta)


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


def organizacion_solicitada(
    x_organization_id: Optional[UUID] = Header(default=None, alias="X-Organization-Id"),
) -> Optional[UUID]:
    """El selector de cuenta (B3, §26): en qué organización pide actuar esta
    petición, si el cliente lo dice.

    `None` —el caso de todo el tráfico hoy, porque ningún cliente manda esta
    cabecera todavía— dice «la de siempre»: `_load_current_user` cae a
    `default_organization_id` exactamente como antes de que existiera esta
    cabecera. Nunca es un error, igual que la marca por `Host` en B3.
    """
    return x_organization_id


def _load_user_by_sub(db: Session, cognito_sub: Optional[str]):
    """La identidad sola: el usuario del token, sin decir nada de en qué
    organización actúa. `_load_current_user` la usa y luego valida la
    membresía; `get_current_user_identity` se queda aquí."""
    from app.models.user import User

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
    return user


def _load_current_user(
    db: Session,
    cognito_sub: Optional[str],
    organization_id: Optional[UUID] = None,
):
    """
    Busca al usuario por `cognito_sub` y valida que la organización en la que
    pide actuar siga siendo una membresía real y activa.

    Punto único: `get_current_user_full`, `resolve_current_organization` y
    `get_current_user_id` delegan aquí en vez de repetir cada una su propia
    consulta — la validación se escribe una sola vez, así que no hay ningún
    camino de los tres que pueda evitarla por accidente.

    `organization_id` es el selector de cuenta: la organización que pide la
    cabecera `X-Organization-Id` (ver `organizacion_solicitada`), o `None`
    para quedarse con `default_organization_id` — el comportamiento de
    siempre. Cualquiera de las dos pasa por el **mismo** chequeo de abajo, así
    que pedir una organización ajena nunca es más permisivo que no pedir
    ninguna.

    Falla cerrado: sin una fila `ACTIVE` en `organization_users` para
    `(user.id, organización solicitada)`, 403 en vez de dejar que el resto del
    API siga resolviendo alertas, dispositivos, unidades o geofences contra
    una organización de la que esta persona no es miembro activo — el hueco
    que dejaba abierto que `DELETE /organizations/{org}/users/{user_id}`
    sólo tocara `users.organization_id` (ver el rediseño de ese endpoint) sin
    corregir la columna cuando a alguien le quedaba otra membresía activa.

    Depende de la migración 035: desde ahí, todo usuario con
    `default_organization_id` no nulo tiene esa fila. Sin ese backfill, esto
    habría bloqueado con 403 a cualquiera invitado por correo antes del
    30/09/2026 — `accept_invitation` nunca creaba la membresía, sólo la
    columna.
    """
    from app.models.organization_user import MembershipStatus, OrganizationUser

    user = _load_user_by_sub(db, cognito_sub)

    organizacion_objetivo = (
        organization_id if organization_id is not None else user.default_organization_id
    )

    has_active_membership = (
        db.query(OrganizationUser)
        .filter(
            OrganizationUser.user_id == user.id,
            OrganizationUser.organization_id == organizacion_objetivo,
            OrganizationUser.status == MembershipStatus.ACTIVE.value,
        )
        .first()
        is not None
    )
    if not has_active_membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sin membresía activa en la organización solicitada",
        )

    if organization_id is not None:
        user._active_organization_id = organization_id

    return user


def resolve_current_organization(
    db: Session, cognito_payload: dict, organization_id: Optional[UUID] = None
) -> UUID:
    """
    Busca el usuario por cognito_sub y retorna la organización en la que
    actúa —la del selector de cuenta si se pidió una, si no la de
    siempre—, ya validada contra una membresía activa real. Ver
    `_load_current_user`.
    """
    return _load_current_user(
        db, cognito_payload.get("sub"), organization_id
    ).organization_id


# Alias de compatibilidad (DEPRECATED)
def resolve_current_client(db: Session, cognito_payload: dict) -> UUID:
    """DEPRECATED: Usar resolve_current_organization"""
    return resolve_current_organization(db, cognito_payload)


def get_current_organization_id(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    organization_id: Optional[UUID] = Depends(organizacion_solicitada),
) -> UUID:
    """
    Dependency que combina autenticación y resolución de organization_id.
    Retorna la organización en la que actúa esta sesión.
    """
    return resolve_current_organization(db, current_user, organization_id)


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
    organization_id: Optional[UUID] = Depends(organizacion_solicitada),
):
    """
    Retorna el objeto User completo del usuario autenticado, con la
    organización en la que actúa ya validada. Ver `_load_current_user`.
    """
    return _load_current_user(db, current_user.get("sub"), organization_id)


def get_current_user_identity(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    El usuario autenticado **sin** validar membresía ni leer
    `X-Organization-Id`. Sólo para endpoints que preguntan por la identidad
    misma y no actúan sobre datos de ninguna organización.

    Hoy lo usa únicamente `GET /auth/organizations`: es la forma de salir de
    una organización por defecto que ya no es válida, así que no puede
    depender de ella. Responde con las membresías de la propia persona y
    nada más, así que no abre nada que `_load_current_user` cierre. No usarlo
    en endpoints que lean o escriban datos de una organización.
    """
    return _load_user_by_sub(db, current_user.get("sub"))


def get_current_user_id(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    organization_id: Optional[UUID] = Depends(organizacion_solicitada),
) -> UUID:
    """
    Retorna el UUID del usuario autenticado. Ver `_load_current_user`.
    """
    return _load_current_user(db, current_user.get("sub"), organization_id).id


def get_current_user_with_role(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    organization_id: Optional[UUID] = Depends(organizacion_solicitada),
) -> tuple:
    """
    Retorna el usuario y su rol organizacional.

    DELEGACIÓN: Usa OrganizationService.get_user_role() como única fuente
    de verdad para roles. Desde el 22/09/2026 esa función no tiene *fallback*:
    el rol sale de `organization_users` y de ningún otro sitio. `is_master` ya
    no concede nada.

    Returns:
        Tuple de (User, OrganizationRole o None)
    """
    user = _load_current_user(db, current_user.get("sub"), organization_id)

    # Obtener rol usando OrganizationService (única fuente de verdad)
    role = OrganizationService.get_user_role(db, user.id, user.organization_id)

    return user, role


def get_auth_solo_servicio(
    required_service: Optional[str] = None,
    required_role: Optional[str] = None,
):
    """Dependencia para el plano de control: **sólo tokens PASETO de servicio**.

    POR QUE EXISTE, Y QUE AGUJERO CIERRA
    ====================================
    `get_auth_cognito_or_paseto` intenta Cognito primero y, si el token es
    válido y el usuario existe en la base, **concede acceso sin mirar ningún
    rol**: `required_service` y `required_role` se aplican únicamente al camino
    PASETO. Sobre un endpoint de usuario eso es correcto y deliberado —`trips`
    y `commands` sirven a la vez a personas y a GAC—, pero bajo `/internal/*`
    significaba que **cualquiera que pudiera iniciar sesión en Nexus podía
    llamar a las veinte rutas de escritura del plano de control**: crear y
    suspender organizaciones, cancelar suscripciones, borrar planes, y
    desactivar a cualquier usuario.

    Comprobado por ejecución el 22/09/2026, no deducido: un usuario normal con
    su token corriente recibió 200 de `PATCH /internal/users/{id}/status` y
    dejó a la víctima en INACTIVE.

    LA REGLA, DICHA UNA VEZ
    =======================
    Un endpoint interno es **servicio a servicio**. No hay persona detrás, así
    que no hay token de persona que valga. Si algún día una interfaz necesita
    entrar aquí con credenciales de usuario, la respuesta no es reabrir esta
    puerta sino darle un endpoint propio con su autorización por rol.
    """

    def _verificar(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> AuthResult:
        payload = decode_service_token(
            credentials.credentials,
            required_service=required_service,
            required_role=required_role,
        )
        if payload:
            return AuthResult(
                auth_type="paseto",
                payload=payload,
                service=payload.get("service"),
                role=payload.get("role"),
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta ruta es de servicio a servicio: requiere un token PASETO válido.",
        )

    return _verificar


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
        de verdad para roles. Sin *fallback*: is_master ya no concede nada.
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
    de verdad para roles. Sin *fallback*: is_master ya no concede nada.

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

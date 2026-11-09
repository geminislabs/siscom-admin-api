import re
from datetime import datetime, time
from datetime import timezone as dt_timezone
from typing import List, Optional, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_cognito_or_paseto
from app.db.session import get_db
from app.models.trip import Trip, TripAlert, TripEvent, TripPoint
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.models.user import User
from app.schemas.trip import (
    TripAlertOut,
    TripDetail,
    TripListResponse,
    TripOut,
    TripPointOut,
)
from app.services.access_control import (
    accessible_refs,
    get_accessible_unit_ids,
    subject_for_user,
)

router = APIRouter()

# Dependencia para autenticación dual (Cognito o PASETO)
get_auth_for_trips = get_auth_cognito_or_paseto(
    required_service="gac",
    required_role="GAC_ADMIN",
)


# ============================================
# Helper Functions
# ============================================


def get_user_from_auth(db: Session, auth: AuthResult) -> Optional[User]:
    """
    Obtiene el objeto User de la base de datos según el tipo de autenticación.

    - Cognito: Busca el usuario por cognito_sub
    - PASETO: Retorna None (acceso sin usuario de BD)

    Args:
        db: Sesión de base de datos
        auth: Resultado de autenticación

    Returns:
        User si es autenticación Cognito, None si es PASETO
    """
    if auth.auth_type == "cognito":
        cognito_sub = auth.payload.get("sub")
        if not cognito_sub:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token Cognito inválido: falta el campo 'sub'",
            )

        user = db.query(User).filter(User.cognito_sub == cognito_sub).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado",
            )
        return user

    # PASETO: No hay usuario de BD, se asume acceso total
    return None


def get_accessible_device_ids(db: Session, user: User) -> List[str]:
    """
    IDs de dispositivos que el usuario puede ver **en algún momento**.

    Sirve para decidir si un dispositivo entra en la respuesta, no para decidir
    qué viajes de ese dispositivo entran: eso lo hace `trips_visibility_filter`,
    que acota por la ventana. Usar solo esta lista dejaría visibles los viajes
    posteriores a que el equipo saliera de la flota — y si se reasignó a otra
    organización, sus viajes con el cliente nuevo.
    """
    refs = accessible_refs(db, subject_for_user(user))
    return [grant.internal_id for grant in refs.devices.values()]


def trips_visibility_filter(db: Session, user: User):
    """
    Filtro SQL que deja pasar solo los viajes ocurridos dentro de una ventana.

    Devuelve None si el usuario no ve ningún dispositivo, para que el llamante
    responda vacío sin construir una consulta imposible.
    """
    refs = accessible_refs(db, subject_for_user(user))

    clauses = []
    for grant in refs.devices.values():
        for window in grant.windows:
            conds = [Trip.device_id == grant.internal_id]
            if window.start is not None:
                conds.append(Trip.start_time >= window.start)
            if window.end is not None:
                conds.append(Trip.start_time < window.end)
            clauses.append(and_(*conds))

    return or_(*clauses) if clauses else None


def check_device_access(db: Session, device_id: str, user: User) -> bool:
    """
    ¿El usuario vio este dispositivo en algún momento?

    Booleano a propósito: responde si el dispositivo puede aparecer, no qué parte
    de su historia. El recorte por ventana lo aplica la consulta.
    """
    return device_id in get_accessible_device_ids(db, user)


def trip_visible(db: Session, trip: Trip, user: User) -> bool:
    """
    ¿El viaje empezó dentro de una ventana en la que el usuario veía su equipo?

    Es la versión de una fila de `trips_visibility_filter`. `check_device_access`
    no basta para un viaje concreto: dice si el equipo se vio alguna vez, y el
    viaje puede ser de antes de la concesión o de después de que el equipo
    saliera de la flota.
    """
    refs = accessible_refs(db, subject_for_user(user))
    inicio = trip.start_time
    if inicio is not None and inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=dt_timezone.utc)
    for grant in refs.devices.values():
        if grant.internal_id != trip.device_id:
            continue
        for window in grant.windows:
            if inicio is None:
                return True
            if (window.start is None or inicio >= window.start) and (
                window.end is None or inicio < window.end
            ):
                return True
    return False


def check_unit_access(db: Session, unit_id: UUID, user: User) -> bool:
    """
    Verifica si el usuario tiene acceso a una unidad específica.
    """
    accessible_units = get_accessible_unit_ids(db, user)
    return unit_id in accessible_units


def parse_day_to_date_range(day: str, tz: str = "UTC") -> Tuple[datetime, datetime]:
    """
    Convierte un día (YYYY-MM-DD) y una zona horaria a un rango de fechas en UTC.

    Args:
        day: Fecha en formato YYYY-MM-DD
        tz: Zona horaria (ej: "America/Mexico_City", default: "UTC")

    Returns:
        Tuple[datetime, datetime]: (start_date, end_date) en UTC

    Raises:
        ValueError: Si el formato del día es inválido o la zona horaria no existe
    """
    # Validar formato del día (YYYY-MM-DD)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
        raise ValueError(f"Formato de día inválido: '{day}'. Use el formato YYYY-MM-DD")

    try:
        # Parsear la fecha
        date_obj = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            f"Fecha inválida: '{day}'. Verifique que sea una fecha válida en formato YYYY-MM-DD"
        )

    try:
        # Obtener la zona horaria
        timezone = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        raise ValueError(
            f"Zona horaria inválida: '{tz}'. Use formato IANA (ej: 'America/Mexico_City')"
        )

    # Crear datetime al inicio del día en la zona horaria especificada
    start_local = datetime.combine(date_obj, time.min, tzinfo=timezone)
    # Crear datetime al final del día (23:59:59.999999)
    end_local = datetime.combine(date_obj, time.max, tzinfo=timezone)

    # Convertir a UTC
    start_utc = start_local.astimezone(ZoneInfo("UTC"))
    end_utc = end_local.astimezone(ZoneInfo("UTC"))

    return start_utc, end_utc


def build_trip_out(trip: Trip) -> TripOut:
    """
    Construye un objeto TripOut a partir de un modelo Trip de la BD.
    Calcula la duración y convierte distancia de metros a kilómetros.
    """
    duration_minutes = None
    if trip.start_time and trip.end_time:
        duration_seconds = (trip.end_time - trip.start_time).total_seconds()
        duration_minutes = round(duration_seconds / 60, 2)

    distance_km = None
    if trip.distance_meters is not None:
        distance_km = round(trip.distance_meters / 1000, 2)

    return TripOut(
        trip_id=trip.trip_id,
        device_id=trip.device_id,
        start_timestamp=trip.start_time,
        end_timestamp=trip.end_time,
        duration_minutes=duration_minutes,
        start_lat=trip.start_lat,
        start_lon=trip.start_lng,
        end_lat=trip.end_lat,
        end_lon=trip.end_lng,
        distance_km=distance_km,
    )


def build_trip_detail(
    db: Session,
    trip: Trip,
    include_alerts: bool = False,
    include_points: bool = False,
    include_events: bool = False,
) -> TripDetail:
    """
    Construye un objeto TripDetail con expansiones opcionales.
    """
    # Calcular campos básicos
    duration_minutes = None
    if trip.start_time and trip.end_time:
        duration_seconds = (trip.end_time - trip.start_time).total_seconds()
        duration_minutes = round(duration_seconds / 60, 2)

    distance_km = None
    if trip.distance_meters is not None:
        distance_km = round(trip.distance_meters / 1000, 2)

    # Obtener información de la unidad asignada
    unit_id = None
    unit_name = None
    # Un viaje en curso no tiene fin todavía: cuenta hasta ahora. Comparar contra
    # `None` con `<=` no es SQL válido y SQLAlchemy lo rechaza (500).
    fin = trip.end_time if trip.end_time is not None else func.now()
    unit_assignment = (
        db.query(UnitDevice, Unit)
        .join(Unit, Unit.id == UnitDevice.unit_id)
        .filter(
            UnitDevice.device_id == trip.device_id,
            or_(
                # Asignación activa
                UnitDevice.unassigned_at.is_(None),
                # O asignación que estaba activa durante el trip
                and_(
                    UnitDevice.assigned_at <= fin,
                    or_(
                        UnitDevice.unassigned_at.is_(None),
                        UnitDevice.unassigned_at >= trip.start_time,
                    ),
                ),
            ),
        )
        .first()
    )

    if unit_assignment:
        unit_id = unit_assignment.Unit.id
        unit_name = unit_assignment.Unit.name

    # Construir objeto base
    trip_detail = TripDetail(
        trip_id=trip.trip_id,
        device_id=trip.device_id,
        start_timestamp=trip.start_time,
        end_timestamp=trip.end_time,
        duration_minutes=duration_minutes,
        start_lat=trip.start_lat,
        start_lon=trip.start_lng,
        end_lat=trip.end_lat,
        end_lon=trip.end_lng,
        distance_km=distance_km,
        unit_id=unit_id,
        unit_name=unit_name,
    )

    # Cargar expansiones si se solicitan
    if include_alerts:
        alerts = (
            db.query(TripAlert)
            .filter(TripAlert.trip_id == trip.trip_id)
            .order_by(TripAlert.timestamp.asc())
            .all()
        )
        trip_detail.alerts = [TripAlertOut.from_db(alert) for alert in alerts]

    if include_points:
        points = (
            db.query(TripPoint)
            .filter(TripPoint.trip_id == trip.trip_id)
            .order_by(TripPoint.timestamp.asc())
            .all()
        )
        trip_detail.points = [TripPointOut.from_db(point) for point in points]

    if include_events:
        events = (
            db.query(TripEvent)
            .filter(TripEvent.trip_id == trip.trip_id)
            .order_by(TripEvent.timestamp.asc())
            .all()
        )
        trip_detail.events = events

    return trip_detail


# ============================================
# Trip Endpoints
# ============================================


@router.get("", response_model=TripListResponse)
def list_trips(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_trips),
    unit_id: Optional[UUID] = Query(None, description="Filtrar por unidad"),
    device_id: Optional[str] = Query(None, description="Filtrar por dispositivo"),
    start_date: Optional[datetime] = Query(
        None, description="Fecha de inicio (ISO 8601). Ignorado si se envía 'day'"
    ),
    end_date: Optional[datetime] = Query(
        None, description="Fecha de fin (ISO 8601). Ignorado si se envía 'day'"
    ),
    day: Optional[str] = Query(
        None,
        description="Día específico en formato YYYY-MM-DD. Si se envía, ignora start_date y end_date",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        examples=["2025-12-03"],
    ),
    tz: str = Query(
        "UTC",
        description="Zona horaria para interpretar 'day' (formato IANA, ej: 'America/Mexico_City')",
        examples=["UTC", "America/Mexico_City", "America/New_York"],
    ),
    limit: int = Query(50, ge=1, le=500, description="Límite de resultados"),
    cursor: Optional[datetime] = Query(
        None, description="Cursor de paginación (timestamp del último trip)"
    ),
    include_alerts: bool = Query(False, description="Incluir alertas en la respuesta"),
    include_points: bool = Query(
        False, description="Incluir puntos GPS en la respuesta"
    ),
    include_events: bool = Query(False, description="Incluir eventos en la respuesta"),
):
    """
    Lista todos los trips accesibles para el usuario autenticado.

    **Autenticación:**
    - Token de Cognito: Usuario autenticado del sistema (aplican permisos)
    - Token PASETO: Requiere service="gac" y role="GAC_ADMIN" (acceso total)

    **Permisos (solo Cognito):**
    - Usuario maestro: puede ver todos los trips de todas las unidades del cliente
    - Usuario regular: solo trips de unidades asignadas en user_units

    **Filtros de fecha (dos opciones mutuamente excluyentes):**

    *Opción 1 - Por día específico:*
    - `day`: Día en formato YYYY-MM-DD (ej: "2025-12-03")
    - `tz`: Zona horaria para interpretar el día (default: UTC, ej: "America/Mexico_City")
    - Filtra trips cuyo `end_time` esté dentro del día especificado

    *Opción 2 - Por rango de fechas:*
    - `start_date`: Fecha de inicio del rango (trips que inician después de esta fecha)
    - `end_date`: Fecha de fin del rango (trips que inician antes de esta fecha)

    **Nota:** Si se envía `day`, los parámetros `start_date` y `end_date` son ignorados.

    **Otros filtros:**
    - `unit_id`: Filtra trips por unidad específica
    - `device_id`: Filtra trips por dispositivo específico
    - `limit`: Número máximo de resultados (default: 50, max: 500)
    - `cursor`: Timestamp del último trip recibido (para paginación)

    **Expansiones:**
    - `include_alerts`: Incluye las alertas de cada trip
    - `include_points`: Incluye los puntos GPS de cada trip (¡puede ser muy grande!)
    - `include_events`: Incluye los eventos de cada trip

    **Nota:** Los filtros de fecha son altamente recomendados para optimizar el rendimiento.
    """
    # Obtener usuario si es Cognito, None si es PASETO
    current_user = get_user_from_auth(db, auth)

    # Procesar parámetro 'day' si está presente
    filter_by_end_time = False
    if day:
        try:
            start_date, end_date = parse_day_to_date_range(day, tz)
            filter_by_end_time = True  # Cuando se usa 'day', filtramos por end_time
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # Construir query base
    query = db.query(Trip)

    # Aplicar filtros de permisos solo si es autenticación Cognito
    if current_user:
        # Cognito: aplicar restricciones de permisos
        visibilidad = trips_visibility_filter(db, current_user)

        if visibilidad is None:
            # Usuario sin acceso a ninguna unidad
            return TripListResponse(
                trips=[], total=0, limit=limit, cursor=None, has_more=False
            )

        # Acota por ventana, no solo por dispositivo: un viaje posterior a que el
        # equipo saliera de la flota no es del usuario, aunque el equipo sí lo
        # fuera antes.
        query = query.filter(visibilidad)

    # Aplicar filtros
    if unit_id:
        # Verificar acceso a la unidad solo si es Cognito
        if current_user and not check_unit_access(db, unit_id, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes acceso a esta unidad",
            )

        # Obtener dispositivos de la unidad
        unit_device_ids = (
            db.query(UnitDevice.device_id)
            .filter(UnitDevice.unit_id == unit_id)
            .distinct()
            .all()
        )
        unit_device_ids = [d[0] for d in unit_device_ids]

        if not unit_device_ids:
            return TripListResponse(
                trips=[], total=0, limit=limit, cursor=None, has_more=False
            )

        query = query.filter(Trip.device_id.in_(unit_device_ids))

    if device_id:
        # Verificar acceso al dispositivo solo si es Cognito
        if current_user and not check_device_access(db, device_id, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes acceso a este dispositivo",
            )
        query = query.filter(Trip.device_id == device_id)

    # Aplicar filtros de fecha
    if filter_by_end_time:
        # Cuando se usa 'day', filtramos por end_time
        if start_date:
            query = query.filter(Trip.end_time >= start_date)
        if end_date:
            query = query.filter(Trip.end_time <= end_date)
    else:
        # Comportamiento original: filtrar por start_time
        if start_date:
            query = query.filter(Trip.start_time >= start_date)
        if end_date:
            query = query.filter(Trip.start_time <= end_date)

    # Aplicar cursor de paginación
    if cursor:
        query = query.filter(Trip.start_time < cursor)

    # Contar total (antes de aplicar limit)
    total = query.count()

    # Ordenar y limitar
    trips = query.order_by(Trip.start_time.desc()).limit(limit + 1).all()

    # Determinar si hay más resultados
    has_more = len(trips) > limit
    if has_more:
        trips = trips[:limit]

    # Construir respuesta
    if include_alerts or include_points or include_events:
        # Usar TripDetail con expansiones
        trip_list = [
            build_trip_detail(
                db,
                trip,
                include_alerts=include_alerts,
                include_points=include_points,
                include_events=include_events,
            )
            for trip in trips
        ]
    else:
        # Usar TripOut básico
        trip_list = [build_trip_out(trip) for trip in trips]

    # Calcular nuevo cursor
    new_cursor = None
    if trips:
        new_cursor = trips[-1].start_time.isoformat()

    return TripListResponse(
        trips=trip_list,
        total=total,
        limit=limit,
        cursor=new_cursor if has_more else None,
        has_more=has_more,
    )


@router.get("/{trip_id}", response_model=TripDetail)
def get_trip(
    trip_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_trips),
    include_alerts: bool = Query(True, description="Incluir alertas del trip"),
    include_points: bool = Query(False, description="Incluir puntos GPS del trip"),
    include_events: bool = Query(False, description="Incluir eventos del trip"),
):
    """
    Obtiene el detalle completo de un trip específico.

    **Autenticación:**
    - Token de Cognito: Usuario autenticado del sistema (aplican permisos)
    - Token PASETO: Requiere service="gac" y role="GAC_ADMIN" (acceso total)

    **Permisos (solo Cognito):**
    - Usuario maestro: puede ver cualquier trip de su cliente
    - Usuario regular: solo trips de dispositivos de sus unidades asignadas

    **Expansiones (query params):**
    - `include_alerts`: Incluye las alertas del trip (default: true)
    - `include_points`: Incluye los puntos GPS del trip (default: false, ¡puede ser muy grande!)
    - `include_events`: Incluye los eventos del trip (default: false)

    **Retorna:**
    - Información completa del trip incluyendo:
      - Datos básicos del viaje
      - Información de la unidad asignada al dispositivo
      - Alertas, puntos y eventos (según los parámetros de expansión)
    """
    # Obtener usuario si es Cognito, None si es PASETO
    current_user = get_user_from_auth(db, auth)

    # Buscar el trip
    trip = db.query(Trip).filter(Trip.trip_id == trip_id).first()

    if not trip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip no encontrado",
        )

    # Verificar acceso solo si es Cognito: al equipo y al momento del viaje.
    if current_user and not trip_visible(db, trip, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este trip",
        )

    # Construir respuesta con expansiones
    return build_trip_detail(
        db,
        trip,
        include_alerts=include_alerts,
        include_points=include_points,
        include_events=include_events,
    )

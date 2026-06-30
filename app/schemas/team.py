"""
Schemas para Teams, Members y Visibility Rules.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.datetime import utcnow


class TeamType(str, Enum):
    """Tipos de team válidos."""

    FAMILY = "FAMILY"
    WORKFORCE = "WORKFORCE"
    FRIENDS = "FRIENDS"
    EMERGENCY = "EMERGENCY"
    TEMPORARY = "TEMPORARY"
    TRAVEL = "TRAVEL"
    EVENT = "EVENT"


class TeamStatus(str, Enum):
    """Estados de team válidos."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class TeamRole(str, Enum):
    """Roles de miembro válidos."""

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    DEPENDENT = "DEPENDENT"
    EMPLOYEE = "EMPLOYEE"
    VIEWER = "VIEWER"
    EMERGENCY_CONTACT = "EMERGENCY_CONTACT"
    GUEST = "GUEST"


class AccessMode(str, Enum):
    """Modos de acceso para reglas de visibilidad."""

    ALWAYS = "ALWAYS"
    SCHEDULED = "SCHEDULED"
    ON_DEMAND = "ON_DEMAND"
    EMERGENCY_ONLY = "EMERGENCY_ONLY"


class TeamCreate(BaseModel):
    """Schema para crear un team."""

    name: str = Field(..., min_length=1, max_length=120)
    type: TeamType
    timezone: str = Field(default="UTC")
    expires_at: Optional[datetime] = None
    auto_delete_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("expires_at")
    @classmethod
    def expires_at_must_be_future(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v <= utcnow():
            raise ValueError("expires_at debe ser una fecha futura")
        return v

    @field_validator("auto_delete_at")
    @classmethod
    def auto_delete_at_must_be_future(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v <= utcnow():
            raise ValueError("auto_delete_at debe ser una fecha futura")
        return v


class TeamUpdate(BaseModel):
    """Schema para actualizar un team."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    timezone: Optional[str] = None
    expires_at: Optional[datetime] = None
    auto_delete_at: Optional[datetime] = None
    metadata: Optional[dict[str, Any]] = None


class TeamOut(BaseModel):
    """Schema de salida para un team."""

    id: UUID
    account_id: UUID
    name: str
    type: TeamType
    status: TeamStatus
    timezone: str
    expires_at: Optional[datetime] = None
    auto_delete_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by_user_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TeamListItem(BaseModel):
    """Schema resumido para listado de teams."""

    id: UUID
    name: str
    type: TeamType
    status: TeamStatus
    timezone: str
    expires_at: Optional[datetime] = None
    my_role: TeamRole
    member_count: int

    class Config:
        from_attributes = True


class TeamStatusOut(BaseModel):
    """Schema para respuestas de cambio de estado."""

    id: UUID
    status: TeamStatus


class TeamMemberCreate(BaseModel):
    """Schema para agregar un miembro."""

    user_id: UUID
    role: TeamRole = Field(default=TeamRole.MEMBER)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TeamMemberUpdate(BaseModel):
    """Schema para actualizar un miembro."""

    role: Optional[TeamRole] = None
    metadata: Optional[dict[str, Any]] = None


class TeamMemberOut(BaseModel):
    """Schema de salida para un miembro."""

    id: UUID
    team_id: UUID
    user_id: UUID
    display_name: Optional[str] = None
    role: TeamRole
    joined_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class MyPermissionsOut(BaseModel):
    """Schema para permisos del usuario actual en un team."""

    team_id: UUID
    user_id: UUID
    role: TeamRole
    permissions: dict[str, bool]


class ScheduleWindow(BaseModel):
    """Ventana de horario para reglas de visibilidad."""

    days: list[str] = Field(..., description="Días: MON, TUE, WED, THU, FRI, SAT, SUN")
    start: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Hora inicio HH:mm")
    end: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Hora fin HH:mm")


class VisibilitySchedule(BaseModel):
    """Estructura de schedule para reglas SCHEDULED."""

    timezone: str = Field(default="UTC")
    windows: list[ScheduleWindow]


class VisibilityRuleCreate(BaseModel):
    """Schema para crear una regla de visibilidad."""

    subject_role: TeamRole
    viewer_role: TeamRole
    access_mode: AccessMode
    schedule: Optional[VisibilitySchedule] = None
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def schedule_required_for_scheduled(self) -> "VisibilityRuleCreate":
        if self.access_mode == AccessMode.SCHEDULED and self.schedule is None:
            raise ValueError("schedule es requerido cuando access_mode es SCHEDULED")
        return self


class VisibilityRuleUpdate(BaseModel):
    """Schema para actualizar una regla de visibilidad."""

    subject_role: Optional[TeamRole] = None
    viewer_role: Optional[TeamRole] = None
    access_mode: Optional[AccessMode] = None
    schedule: Optional[VisibilitySchedule] = None
    is_active: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def schedule_required_for_scheduled(self) -> "VisibilityRuleUpdate":
        if self.access_mode == AccessMode.SCHEDULED and self.schedule is None:
            raise ValueError("schedule es requerido cuando access_mode es SCHEDULED")
        return self


class VisibilityRuleStatusOut(BaseModel):
    """Schema para respuestas de activar/desactivar regla."""

    id: UUID
    is_active: bool


class VisibilityRuleOut(BaseModel):
    """Schema de salida para una regla de visibilidad."""

    id: UUID
    team_id: UUID
    subject_role: TeamRole
    viewer_role: TeamRole
    access_mode: AccessMode
    schedule: Optional[dict[str, Any]] = None
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TeamActivateRequest(BaseModel):
    """Request opcional para reactivar un team."""

    expires_at: Optional[datetime] = None


class InviteMethod(str, Enum):
    """Métodos de invitación válidos."""

    QR = "QR"
    LINK = "LINK"
    EMAIL = "EMAIL"
    PHONE = "PHONE"


class TeamInviteCreate(BaseModel):
    """Schema para crear una invitación."""

    invite_method: InviteMethod
    invited_role: TeamRole = Field(default=TeamRole.MEMBER)
    expires_at: datetime
    max_uses: int = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("expires_at")
    @classmethod
    def expires_at_must_be_future(cls, v: datetime) -> datetime:
        if v <= utcnow():
            raise ValueError("expires_at debe ser una fecha futura")
        return v


class TeamInviteOut(BaseModel):
    """Schema de salida para una invitación (sin token)."""

    id: UUID
    team_id: UUID
    invite_method: InviteMethod
    invited_role: TeamRole
    expires_at: datetime
    max_uses: int
    used_count: int
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    class Config:
        from_attributes = True


class TeamInviteCreatedOut(TeamInviteOut):
    """Schema de salida al crear invitación (incluye token una sola vez)."""

    token: str
    invite_url: str


class TeamInviteRevokeOut(BaseModel):
    """Schema para respuesta de revocar invitación."""

    id: UUID
    is_active: bool


class InvitePublicOut(BaseModel):
    """Información pública mínima de una invitación."""

    team_id: UUID
    team_name: str
    team_type: TeamType
    invited_role: TeamRole
    expires_at: datetime


class InviteAcceptOut(BaseModel):
    """Schema de respuesta al aceptar una invitación."""

    team_id: UUID
    member_id: UUID
    role: TeamRole

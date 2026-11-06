from datetime import datetime
from typing import List, Optional

from sqlalchemy import CheckConstraint, Column, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
from sqlmodel import Field, SQLModel


class ClientVersionPolicy(SQLModel, table=True):
    """
    Qué versiones de las apps móviles se aceptan, por plataforma (migración 047).

    Ver `app/services/client_version_policy.py` para cómo se interpreta, y
    `docs/runbooks/politica-de-versiones.md` para cómo se cambia.
    """

    __tablename__ = "client_version_policy"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('ios', 'android')", name="ck_client_version_policy_platform"
        ),
    )

    platform: str = Field(sa_column=Column(Text, primary_key=True))
    min_supported_version: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    latest_version: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    blocked_versions: List[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
        ),
    )
    store_url: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
        )
    )
    updated_by: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

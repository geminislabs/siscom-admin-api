"""Add unit_profile and vehicle_profile tables

Revision ID: 010_unit_profiles
Revises: 009_add_preparado
Create Date: 2025-11-28

Cambios principales:
- Crea tabla unit_profile para almacenar información universal del perfil de unidad
- Crea tabla vehicle_profile para almacenar información específica de vehículos
- Agrega índices para mejorar rendimiento
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "010_unit_profiles"
down_revision = "009_add_preparado"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Crea tablas unit_profile y vehicle_profile
    """

    # ============================================
    # PASO 1: Crear tabla unit_profile
    # ============================================
    op.create_table(
        "unit_profile",
        sa.Column(
            "profile_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "unit_id",
            UUID(as_uuid=True),
            sa.ForeignKey("units.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("unit_type", sa.Text(), nullable=False),
        sa.Column("icon_type", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("serial", sa.Text(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Índice para unit_type
    op.create_index("idx_unit_profile_type", "unit_profile", ["unit_type"])

    # ============================================
    # PASO 2: Crear tabla vehicle_profile
    # ============================================
    op.create_table(
        "vehicle_profile",
        sa.Column(
            "unit_id",
            UUID(as_uuid=True),
            sa.ForeignKey("unit_profile.unit_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("plate", sa.Text(), nullable=True),
        sa.Column("vin", sa.Text(), nullable=True),
        sa.Column("fuel_type", sa.Text(), nullable=True),
        sa.Column("passengers", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Índice para plate (búsqueda por placa)
    op.create_index("idx_vehicle_plate", "vehicle_profile", ["plate"])


def downgrade() -> None:
    """
    Revierte los cambios eliminando las tablas
    """

    # Eliminar tablas en orden inverso
    op.drop_table("vehicle_profile")
    op.drop_table("unit_profile")

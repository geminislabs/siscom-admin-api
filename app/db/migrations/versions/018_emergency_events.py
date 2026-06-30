"""Create team.emergency_events table

Revision ID: 018_emergency_events
Revises: 017_team_invites
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "018_emergency_events"
down_revision = "017_team_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # Crear tabla emergency_events si no existe
    if "emergency_events" not in inspector.get_table_names(schema="team"):
        op.create_table(
            "emergency_events",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column(
                "team_id", postgresql.UUID(as_uuid=True), nullable=False
            ),
            sa.Column(
                "triggered_by_user_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("emergency_type", sa.Text(), nullable=False),
            sa.Column(
                "status",
                sa.Text(),
                server_default=sa.text("'ACTIVE'"),
                nullable=False,
            ),
            sa.Column(
                "started_at",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["team_id"],
                ["team.teams.id"],
                name=op.f("fk_emergency_events_team_id_teams"),
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["triggered_by_user_id"],
                ["users.id"],
                name=op.f("fk_emergency_events_triggered_by_user_id_users"),
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_emergency_events")),
            schema="team",
        )
        
        # Crear índice compuesto para consultas por team y status
        op.create_index(
            op.f("idx_emergency_events_team_status"),
            "emergency_events",
            ["team_id", "status"],
            schema="team",
        )
        
        # Agregar constraint de status
        op.create_check_constraint(
            "chk_emergency_status",
            "emergency_events",
            sa.text("status IN ('ACTIVE', 'RESOLVED', 'CANCELLED')"),
            schema="team",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    if "emergency_events" in inspector.get_table_names(schema="team"):
        op.drop_index(
            op.f("idx_emergency_events_team_status"),
            table_name="emergency_events",
            schema="team",
        )
        op.drop_table("emergency_events", schema="team")

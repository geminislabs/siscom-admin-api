"""Create team schema with teams, members, and visibility_rules tables

Revision ID: 016_team_core
Revises: 015_subscriptions_active_units
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "016_team_core"
down_revision = "015_subscriptions_active_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    op.execute("CREATE SCHEMA IF NOT EXISTS team")

    existing_tables = inspector.get_table_names(schema="team")

    if "teams" not in existing_tables:
        op.create_table(
            "teams",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("type", sa.Text(), nullable=False),
            sa.Column(
                "status", sa.Text(), server_default=sa.text("'ACTIVE'"), nullable=False
            ),
            sa.Column(
                "timezone", sa.Text(), server_default=sa.text("'UTC'"), nullable=False
            ),
            sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column(
                "auto_delete_at", postgresql.TIMESTAMP(timezone=True), nullable=True
            ),
            sa.Column(
                "metadata",
                postgresql.JSONB(),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True
            ),
            sa.Column(
                "created_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["account_id"], ["accounts.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.CheckConstraint(
                "type IN ('FAMILY', 'WORKFORCE', 'FRIENDS', 'EMERGENCY', "
                "'TEMPORARY', 'TRAVEL', 'EVENT')",
                name="chk_team_type",
            ),
            sa.CheckConstraint(
                "status IN ('ACTIVE', 'SUSPENDED', 'EXPIRED', 'DELETED')",
                name="chk_team_status",
            ),
            schema="team",
        )
        op.create_index("idx_team_account", "teams", ["account_id"], schema="team")
        op.create_index("idx_team_type", "teams", ["type"], schema="team")
        op.create_index("idx_team_expires_at", "teams", ["expires_at"], schema="team")

    if "members" not in existing_tables:
        op.create_table(
            "members",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("role", sa.Text(), nullable=False),
            sa.Column(
                "invited_by_user_id", postgresql.UUID(as_uuid=True), nullable=True
            ),
            sa.Column(
                "joined_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "metadata",
                postgresql.JSONB(),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["team_id"], ["team.teams.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["invited_by_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.CheckConstraint(
                "role IN ('OWNER', 'ADMIN', 'MEMBER', 'DEPENDENT', 'EMPLOYEE', "
                "'VIEWER', 'EMERGENCY_CONTACT', 'GUEST')",
                name="chk_member_role",
            ),
            sa.UniqueConstraint("team_id", "user_id", name="uq_team_member"),
            schema="team",
        )
        op.create_index("idx_team_members_team", "members", ["team_id"], schema="team")
        op.create_index("idx_team_members_user", "members", ["user_id"], schema="team")

    if "visibility_rules" not in existing_tables:
        op.create_table(
            "visibility_rules",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("subject_role", sa.Text(), nullable=False),
            sa.Column("viewer_role", sa.Text(), nullable=False),
            sa.Column("access_mode", sa.Text(), nullable=False),
            sa.Column("schedule", postgresql.JSONB(), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean(),
                server_default=sa.text("true"),
                nullable=False,
            ),
            sa.Column(
                "metadata",
                postgresql.JSONB(),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                postgresql.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["team_id"], ["team.teams.id"], ondelete="CASCADE"),
            sa.CheckConstraint(
                "access_mode IN ('ALWAYS', 'SCHEDULED', 'ON_DEMAND', 'EMERGENCY_ONLY')",
                name="chk_access_mode",
            ),
            schema="team",
        )
        op.create_index(
            "idx_visibility_team", "visibility_rules", ["team_id"], schema="team"
        )
        op.create_index(
            "idx_visibility_rules_team_active",
            "visibility_rules",
            ["team_id", "is_active"],
            schema="team",
        )


def downgrade() -> None:
    op.drop_table("visibility_rules", schema="team")
    op.drop_table("members", schema="team")
    op.drop_table("teams", schema="team")
    op.execute("DROP SCHEMA IF EXISTS team CASCADE")

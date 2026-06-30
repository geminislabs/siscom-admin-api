"""Create team.invites table

Revision ID: 017_team_invites
Revises: 016_team_core
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "017_team_invites"
down_revision = "016_team_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names(schema="team")

    if "invites" not in existing_tables:
        op.create_table(
            "invites",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column(
                "created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False
            ),
            sa.Column("invite_method", sa.Text(), nullable=False),
            sa.Column("invited_role", sa.Text(), nullable=False),
            sa.Column("token_hash", sa.Text(), nullable=False),
            sa.Column(
                "expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False
            ),
            sa.Column(
                "max_uses", sa.Integer(), server_default=sa.text("1"), nullable=False
            ),
            sa.Column(
                "used_count", sa.Integer(), server_default=sa.text("0"), nullable=False
            ),
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
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["team_id"], ["team.teams.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"], ["users.id"], ondelete="CASCADE"
            ),
            sa.CheckConstraint(
                "invite_method IN ('QR', 'LINK', 'EMAIL', 'PHONE')",
                name="chk_invite_method",
            ),
            sa.CheckConstraint(
                "invited_role IN ('OWNER', 'ADMIN', 'MEMBER', 'DEPENDENT', "
                "'EMPLOYEE', 'VIEWER', 'EMERGENCY_CONTACT', 'GUEST')",
                name="chk_invited_role",
            ),
            sa.CheckConstraint("max_uses >= 1", name="chk_invite_max_uses"),
            schema="team",
        )
        op.create_index("idx_team_invites_team", "invites", ["team_id"], schema="team")
        op.create_index(
            "idx_team_invites_token_hash",
            "invites",
            ["token_hash"],
            schema="team",
        )
        op.create_index(
            "idx_team_invites_active",
            "invites",
            ["team_id", "is_active"],
            schema="team",
        )


def downgrade() -> None:
    op.drop_table("invites", schema="team")

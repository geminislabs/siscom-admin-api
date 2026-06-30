"""Create mobility.devices table

Revision ID: 019_mobility_devices
Revises: 018_emergency_events
Create Date: 2026-06-30 12:54:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "019_mobility_devices"
down_revision = "018_emergency_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create mobility schema if it doesn't exist
    op.execute("CREATE SCHEMA IF NOT EXISTS mobility")

    # Create mobility.devices table
    op.create_table(
        "devices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_type", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("device_name", sa.Text(), nullable=True),
        sa.Column("external_device_id", sa.Text(), nullable=True),
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.Column("os_version", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        # Note: notification_device_id FK omitted because user_devices table doesn't exist yet
        sa.Column(
            "notification_device_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        schema="mobility",
    )

    # Create unique index for notification_device_id (partial index where not null)
    op.create_index(
        "uq_mobility_devices_notification_device",
        "devices",
        ["notification_device_id"],
        unique=True,
        schema="mobility",
        postgresql_where=sa.text("notification_device_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Drop index first
    op.drop_index(
        "uq_mobility_devices_notification_device",
        table_name="devices",
        schema="mobility",
    )

    # Drop table
    op.drop_table("devices", schema="mobility")

    # Drop schema (will fail if other tables exist, which is fine)
    op.execute("DROP SCHEMA IF EXISTS mobility CASCADE")

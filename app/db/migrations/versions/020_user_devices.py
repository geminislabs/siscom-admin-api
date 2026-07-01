"""Create user_devices table for push notifications

Revision ID: 020_user_devices
Revises: 019_mobility_devices
Create Date: 2026-06-30 13:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "020_user_devices"
down_revision = "019_mobility_devices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create user_devices table for push notifications
    op.create_table(
        "user_devices",
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
        sa.Column("device_token", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("endpoint_arn", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "last_seen_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        schema="public",
    )

    # Create indexes
    op.create_index(
        "idx_user_devices_user_id", "user_devices", ["user_id"], schema="public"
    )
    op.create_index(
        "idx_user_devices_device_token",
        "user_devices",
        ["device_token"],
        schema="public",
    )

    # Now add the FK to mobility.devices since user_devices exists
    op.create_foreign_key(
        "mobility_devices_notification_device_id_fkey",
        "devices",
        "user_devices",
        ["notification_device_id"],
        ["id"],
        source_schema="mobility",
        referent_schema="public",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Drop FK first
    op.drop_constraint(
        "mobility_devices_notification_device_id_fkey",
        "devices",
        type_="foreignkey",
        schema="mobility",
    )

    # Drop indexes
    op.drop_index(
        "idx_user_devices_device_token", table_name="user_devices", schema="public"
    )
    op.drop_index(
        "idx_user_devices_user_id", table_name="user_devices", schema="public"
    )

    # Drop table
    op.drop_table("user_devices", schema="public")

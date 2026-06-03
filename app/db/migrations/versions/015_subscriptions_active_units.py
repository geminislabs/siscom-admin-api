"""Add subscriptions.active_units for manual billing

Revision ID: 015_subscriptions_active_units
Revises: 014_rename_users_client_id
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "015_subscriptions_active_units"
down_revision = "014_rename_users_client_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("subscriptions")}
    if "active_units" not in columns:
        op.add_column(
            "subscriptions",
            sa.Column(
                "active_units",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("subscriptions")}
    if "active_units" in columns:
        op.drop_column("subscriptions", "active_units")

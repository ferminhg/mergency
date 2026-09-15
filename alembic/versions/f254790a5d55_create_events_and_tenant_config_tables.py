"""create events and tenant_config tables

Revision ID: f254790a5d55
Revises: 
Create Date: 2026-09-14 21:20:42.272955

"""
import sqlalchemy as sa

from alembic import op

revision = 'f254790a5d55'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("installation_id", sa.Integer, nullable=False),
        sa.Column("repo", sa.String, nullable=False),
        sa.Column("sha", sa.String, nullable=False),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("owner", sa.String, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "installation_id", "repo", "sha", "event_type", "owner", name="ux_events_dedupe_key"
        ),
    )
    op.create_index(
        "ix_events_budget_query",
        "events",
        ["installation_id", "owner", "ts"],
    )
    op.create_table(
        "tenant_config",
        sa.Column("installation_id", sa.Integer, primary_key=True),
        sa.Column("rolling_window_days", sa.Integer, nullable=False),
        sa.Column("default_team", sa.String, nullable=False),
        sa.Column("max_events_per_window", sa.Integer, nullable=False),
        sa.Column("warn_threshold_pct", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tenant_config")
    op.drop_index("ix_events_budget_query", table_name="events")
    op.drop_table("events")

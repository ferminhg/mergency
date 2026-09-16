"""add_check_name_to_events

Revision ID: d2b560ad4924
Revises: f254790a5d55
Create Date: 2026-09-16 08:52:16.173835

"""
import sqlalchemy as sa

from alembic import op

revision = 'd2b560ad4924'
down_revision = 'f254790a5d55'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("check_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "check_name")

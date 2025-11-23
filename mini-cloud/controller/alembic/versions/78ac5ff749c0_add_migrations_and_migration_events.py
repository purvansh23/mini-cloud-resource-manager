"""add migrations and migration_events

Revision ID: 78ac5ff749c0
Revises: 
Create Date: 2025-11-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "78ac5ff749c0"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # create migrations table
    op.create_table(
        "migrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("vm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_host", sa.String(), nullable=False),
        sa.Column("target_host", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("client_request_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
    )

    # create migration_events table
    op.create_table(
        "migration_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("migration_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("migrations.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("level", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_table("migration_events")
    op.drop_table("migrations")

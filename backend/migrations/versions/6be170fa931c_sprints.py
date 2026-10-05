"""Owner-published contribution sprints.

Revision ID: 6be170fa931c
Revises: b194e870a061
"""
from alembic import op
import sqlalchemy as sa

revision = "6be170fa931c"
down_revision = "b194e870a061"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("sprints",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("slug", sa.String(80), unique=True, nullable=False),
        sa.Column("title", sa.JSON(), nullable=False), sa.Column("description", sa.JSON(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_hours", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("ends_at > starts_at"), sa.CheckConstraint("response_hours BETWEEN 1 AND 168"),
        sa.CheckConstraint("status IN ('DRAFT','PUBLISHED','PAUSED')"))
    op.create_index("ix_sprints_project_id", "sprints", ["project_id"])
    op.create_table("sprint_tasks",
        sa.Column("sprint_id", sa.String(64), sa.ForeignKey("sprints.id"), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.id"), primary_key=True))


def downgrade():
    op.drop_table("sprint_tasks")
    op.drop_table("sprints")

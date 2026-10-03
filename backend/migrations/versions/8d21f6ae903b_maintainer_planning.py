"""Owner goals, proposed improvements, and frozen task contracts."""
from alembic import op
import sqlalchemy as sa

revision = "8d21f6ae903b"
down_revision = "5c4267c97e04"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("project_goals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("priority BETWEEN 1 AND 5"),
        sa.CheckConstraint("status IN ('ACTIVE','PAUSED','COMPLETED')"))
    op.create_index("ix_project_goals_project_id", "project_goals", ["project_id"])
    op.create_table("improvements",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("goal_id", sa.String(64), sa.ForeignKey("project_goals.id"), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("in_scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("out_of_scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("kind", sa.String(30), nullable=False, server_default="FEATURE"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(30), nullable=False, server_default="PROPOSED"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("priority BETWEEN 1 AND 5"),
        sa.CheckConstraint("kind IN ('FEATURE','BUG','DOCS','TESTS','PERFORMANCE')"),
        sa.CheckConstraint("status IN ('PROPOSED','APPROVED','IN_PROGRESS','ACCEPTANCE','DONE','REJECTED')"))
    op.create_index("ix_improvements_project_id", "improvements", ["project_id"])
    op.create_index("ix_improvements_goal_id", "improvements", ["goal_id"])
    op.add_column("tasks", sa.Column("improvement_id", sa.String(64), nullable=True))
    op.create_foreign_key("fk_tasks_improvement_id", "tasks", "improvements", ["improvement_id"], ["id"])
    op.create_index("ix_tasks_improvement_id", "tasks", ["improvement_id"])
    op.create_table("planning_actions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_planning_actions_project_id", "planning_actions", ["project_id"])


def downgrade():
    op.drop_table("planning_actions")
    op.drop_index("ix_tasks_improvement_id", table_name="tasks")
    op.drop_constraint("fk_tasks_improvement_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "improvement_id")
    op.drop_table("improvements")
    op.drop_table("project_goals")

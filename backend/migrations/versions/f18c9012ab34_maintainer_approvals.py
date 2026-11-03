"""Record exact-head project-owner acceptance separately from independent reviews."""
from alembic import op
import sqlalchemy as sa

revision = "f18c9012ab34"
down_revision = "6be170fa931c"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "maintainer_approvals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("submission_id", sa.String(64), sa.ForeignKey("submissions.id"), nullable=False),
        sa.Column("head_sha", sa.String(64), nullable=False),
        sa.Column("maintainer_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("submission_id", "head_sha", "maintainer_id"),
    )
    op.create_index("ix_maintainer_approvals_submission_id", "maintainer_approvals", ["submission_id"])


def downgrade():
    op.drop_table("maintainer_approvals")

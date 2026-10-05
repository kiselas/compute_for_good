"""Index accepted-outcome recognition without changing ledger semantics."""
from alembic import op

revision = "b194e870a061"
down_revision = "d76394fa81b2"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_index("ix_impact_credits_user_id", "impact_credits", ["user_id"])
    op.create_index("ix_impact_credits_created_at", "impact_credits", ["created_at"])


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index("ix_impact_credits_created_at", table_name="impact_credits")
    op.drop_index("ix_impact_credits_user_id", table_name="impact_credits")

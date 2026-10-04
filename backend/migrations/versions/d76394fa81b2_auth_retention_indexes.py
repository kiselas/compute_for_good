"""Index authentication expiry and revocation for bounded retention sweeps.

Revision ID: d76394fa81b2
Revises: 8d21f6ae903b
"""
from alembic import op

revision = "d76394fa81b2"
down_revision = "8d21f6ae903b"
branch_labels = None
depends_on = None

INDEXES = (
    ("browser_sessions", "expires_at"),
    ("browser_sessions", "revoked_at"),
    ("api_credentials", "expires_at"),
    ("api_credentials", "revoked_at"),
    ("oauth_grants", "expires_at"),
    ("github_login_states", "expires_at"),
)


def upgrade():
    # Initial launch tables are small. A lock timeout fails this transaction
    # cleanly rather than holding deployment behind an active auth transaction.
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table, column in INDEXES:
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table, column in reversed(INDEXES):
        op.drop_index(f"ix_{table}_{column}", table_name=table)

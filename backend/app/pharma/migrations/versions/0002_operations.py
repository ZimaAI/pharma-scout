"""Shared login throttling and workspace configuration safety."""

from alembic import op

revision = "pharma_0002"
down_revision = "pharma_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE TABLE pharma_login_attempt (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), identity_hash char(64) NOT NULL, created_at timestamptz NOT NULL DEFAULT now())")
    op.execute("CREATE INDEX pharma_login_attempt_lookup ON pharma_login_attempt(identity_hash,created_at)")


def downgrade():
    op.execute("DROP TABLE pharma_login_attempt")

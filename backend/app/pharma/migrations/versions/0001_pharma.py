"""PharmaScope transactional domain schema and immutable evidence triggers."""

from pathlib import Path

from alembic import op

revision = "pharma_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    sql = (Path(__file__).parents[1] / "schema.sql").read_text(encoding="utf-8")
    sql = sql.replace("BEGIN;\n", "", 1).rsplit("COMMIT;", 1)[0]
    op.get_bind().exec_driver_sql(sql.replace("%", "%%"))


def downgrade():
    raise RuntimeError("Restore a verified backup; published evidence cannot be destructively downgraded.")

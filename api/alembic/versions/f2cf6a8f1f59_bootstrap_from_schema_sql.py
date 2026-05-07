"""bootstrap from schema.sql

Revision ID: f2cf6a8f1f59
Revises:
Create Date: 2026-05-07 10:19:34.536051

"""
from collections.abc import Sequence
from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2cf6a8f1f59"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# api/alembic/versions/<this>.py → repo root → db/schema.sql
SCHEMA_SQL = Path(__file__).resolve().parents[3] / "db" / "schema.sql"


def upgrade() -> None:
    sql = SCHEMA_SQL.read_text()
    op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")

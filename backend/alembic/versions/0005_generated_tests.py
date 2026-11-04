"""Generated tests attached to a review.

Revision ID: 0005_generated_tests
Revises: 0004_finding_snippet
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_generated_tests"
down_revision: str | None = "0004_finding_snippet"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.add_column(sa.Column("generated_tests", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("tests_generated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.drop_column("tests_generated_at")
        batch_op.drop_column("generated_tests")

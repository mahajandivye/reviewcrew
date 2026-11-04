"""Add reviews.source: reviews can now be created from the app, not only webhooks.

Revision ID: 0002_review_source
Revises: 0001_initial
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_review_source"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch_alter_table emits plain ALTER on Postgres and a table rebuild on
    # SQLite (which cannot ADD a NOT NULL column without a default).
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.String(length=20), nullable=False, server_default="github")
        )


def downgrade() -> None:
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.drop_column("source")

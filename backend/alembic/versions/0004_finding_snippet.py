"""Finding.original_snippet - code context for before/after fixes.

Revision ID: 0004_finding_snippet
Revises: 0003_conversations
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_finding_snippet"
down_revision: str | None = "0003_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("findings") as batch_op:
        batch_op.add_column(sa.Column("original_snippet", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("findings") as batch_op:
        batch_op.drop_column("original_snippet")

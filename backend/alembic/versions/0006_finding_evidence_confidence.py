"""Store evidence quotes and confidence on each finding.

Revision ID: 0006_finding_evidence_confidence
Revises: 0005_generated_tests
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_finding_evidence_confidence"
down_revision: str | None = "0005_generated_tests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("findings") as batch_op:
        batch_op.add_column(sa.Column("evidence", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.65")
        )


def downgrade() -> None:
    with op.batch_alter_table("findings") as batch_op:
        batch_op.drop_column("confidence")
        batch_op.drop_column("evidence")

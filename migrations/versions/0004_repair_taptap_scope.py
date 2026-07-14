"""Repair TapTap reviews assigned to the Bilibili discovery scope."""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_repair_taptap_scope"
down_revision: str | None = "0003_analysis_modes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE content_items SET source_scope = 'taptap' "
        "WHERE platform = 'taptap' AND source_scope != 'taptap'"
    )


def downgrade() -> None:
    # The previous value cannot be reconstructed safely.
    pass

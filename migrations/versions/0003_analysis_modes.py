"""Rename the legacy enhanced analysis mode to full."""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_analysis_modes"
down_revision: str | None = "0002_sources_auth_sharing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE jobs SET analysis_mode = 'full' WHERE analysis_mode = 'enhanced'")


def downgrade() -> None:
    op.execute("UPDATE jobs SET analysis_mode = 'enhanced' WHERE analysis_mode = 'full'")

"""Add source partitions, official accounts, completeness, and report shares."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_sources_auth_sharing"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("official_bilibili_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("official_mid", sa.String(40), nullable=True))
        batch.add_column(
            sa.Column("include_discovery", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(
            sa.Column("include_taptap", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("taptap_app_url", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("collection_metrics", sa.JSON(), nullable=False, server_default="{}")
        )
        batch.create_index("ix_jobs_official_mid", ["official_mid"])

    with op.batch_alter_table("videos") as batch:
        batch.add_column(
            sa.Column(
                "source_scope",
                sa.String(32),
                nullable=False,
                server_default="bilibili_discovery",
            )
        )
        batch.add_column(sa.Column("official_mid", sa.String(40), nullable=True))
        batch.create_index("ix_videos_source_scope", ["source_scope"])

    with op.batch_alter_table("source_apps") as batch:
        batch.add_column(
            sa.Column("source_scope", sa.String(32), nullable=False, server_default="taptap")
        )
        batch.create_index("ix_source_apps_source_scope", ["source_scope"])

    with op.batch_alter_table("content_items") as batch:
        batch.add_column(
            sa.Column(
                "source_scope",
                sa.String(32),
                nullable=False,
                server_default="bilibili_discovery",
            )
        )
        batch.add_column(sa.Column("parent_external_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("reply_depth", sa.Integer(), nullable=False, server_default="0"))
        batch.create_index("ix_content_items_source_scope", ["source_scope"])
        batch.create_index("ix_content_items_parent_external_id", ["parent_external_id"])

    op.create_table(
        "official_accounts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("mid", sa.String(40), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("expected_video_count", sa.Integer(), nullable=True),
        sa.Column("collected_video_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_meta", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_official_accounts_job_id", "official_accounts", ["job_id"])
    op.create_index("ix_official_accounts_mid", "official_accounts", ["mid"])

    op.create_table(
        "report_shares",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_report_shares_job_id", "report_shares", ["job_id"])
    op.create_index("ix_report_shares_token_hash", "report_shares", ["token_hash"])
    op.create_index("ix_report_shares_expires_at", "report_shares", ["expires_at"])


def downgrade() -> None:
    op.drop_table("report_shares")
    op.drop_table("official_accounts")
    with op.batch_alter_table("content_items") as batch:
        batch.drop_index("ix_content_items_parent_external_id")
        batch.drop_index("ix_content_items_source_scope")
        batch.drop_column("reply_depth")
        batch.drop_column("parent_external_id")
        batch.drop_column("source_scope")
    with op.batch_alter_table("source_apps") as batch:
        batch.drop_index("ix_source_apps_source_scope")
        batch.drop_column("source_scope")
    with op.batch_alter_table("videos") as batch:
        batch.drop_index("ix_videos_source_scope")
        batch.drop_column("official_mid")
        batch.drop_column("source_scope")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_official_mid")
        batch.drop_column("collection_metrics")
        batch.drop_column("taptap_app_url")
        batch.drop_column("include_taptap")
        batch.drop_column("include_discovery")
        batch.drop_column("official_mid")
        batch.drop_column("official_bilibili_url")

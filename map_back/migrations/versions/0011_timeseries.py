"""Immutable time series bound to published asset versions."""
from alembic import op
import sqlalchemy as sa

revision = "0011_timeseries"
down_revision = "0010_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("time_series_snapshots",
        sa.Column("asset_id", sa.String(36), primary_key=True),
        sa.Column("asset_version", sa.String(32), primary_key=True),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id", "asset_version"],
                                ["asset_versions.asset_id", "asset_versions.version"], ondelete="CASCADE"))
    op.execute("CREATE TRIGGER time_series_immutable BEFORE UPDATE ON time_series_snapshots "
               "BEGIN SELECT RAISE(ABORT, '时序快照不可修改'); END")


def downgrade():
    op.drop_table("time_series_snapshots")

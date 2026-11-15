"""Mark immutable 3D Tiles versions with geometry calibration baked in."""
from alembic import op
import sqlalchemy as sa

revision = "0020_tiles_calibration"
down_revision = "0019_display_regions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("asset_versions", sa.Column("tiles_calibrated", sa.Boolean(),
                                              nullable=False, server_default=sa.false()))
    op.execute("CREATE TRIGGER asset_calibration_immutable BEFORE UPDATE OF tiles_calibrated "
               "ON asset_versions BEGIN SELECT RAISE(ABORT, '资产校准状态不可修改'); END")


def downgrade():
    op.execute("DROP TRIGGER asset_calibration_immutable")
    op.drop_column("asset_versions", "tiles_calibrated")

"""Persist optional terrain alignment for 3D Tiles layers."""
from alembic import op
import sqlalchemy as sa

revision = "0017_tiles_height"
down_revision = "0016_render_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("layers", sa.Column("tiles_height_offset_m", sa.Float(), nullable=False, server_default="0"))
    op.add_column("layers", sa.Column("tiles_ground_anchor", sa.JSON()))
    op.add_column("builtin_layer_states", sa.Column("tiles_placements", sa.JSON()))


def downgrade():
    op.drop_column("builtin_layer_states", "tiles_placements")
    op.drop_column("layers", "tiles_ground_anchor")
    op.drop_column("layers", "tiles_height_offset_m")

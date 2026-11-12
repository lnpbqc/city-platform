"""Store an explicit terrain alignment preference for registered 3D Tiles."""
from alembic import op
import sqlalchemy as sa

revision = "0018_tiles_terrain_alignment"
down_revision = "0017_tiles_height"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("layers", sa.Column("tiles_align_to_terrain", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("layers", "tiles_align_to_terrain")

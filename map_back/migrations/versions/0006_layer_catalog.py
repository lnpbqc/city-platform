"""Persist catalog order and default layer states without changing resource URLs."""
from alembic import op
import sqlalchemy as sa

revision = "0006_layer_catalog"
down_revision = "0005_asset_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("layers", sa.Column("map_order", sa.Integer(), nullable=False, server_default="100"))
    op.add_column("layers", sa.Column("orderable", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("builtin_layer_states", sa.Column("id", sa.String(80), primary_key=True),
                    sa.Column("map_attached", sa.Boolean(), nullable=False),
                    sa.Column("map_visible", sa.Boolean(), nullable=False),
                    sa.Column("map_opacity", sa.Float(), nullable=False),
                    sa.Column("map_order", sa.Integer(), nullable=False))


def downgrade():
    op.drop_table("builtin_layer_states")
    op.drop_column("layers", "orderable")
    op.drop_column("layers", "map_order")

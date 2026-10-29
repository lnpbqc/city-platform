"""Index immutable asset features and their WGS84 envelopes."""
from alembic import op
import sqlalchemy as sa

revision = "0007_object_index"
down_revision = "0006_layer_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("object_indexes",
                    sa.Column("asset_id", sa.String(36), primary_key=True),
                    sa.Column("asset_version", sa.String(32), primary_key=True),
                    sa.Column("status", sa.String(16), nullable=False), sa.Column("error", sa.String(1000), nullable=False),
                    sa.ForeignKeyConstraint(["asset_id", "asset_version"], ["asset_versions.asset_id", "asset_versions.version"], ondelete="CASCADE"))
    op.create_table("spatial_objects", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("asset_id", sa.String(36), nullable=False), sa.Column("asset_version", sa.String(32), nullable=False),
                    sa.Column("feature_index", sa.Integer(), nullable=False), sa.Column("type", sa.String(80), nullable=False),
                    sa.Column("name", sa.String()), sa.Column("height_m", sa.Float()), sa.Column("level", sa.String()),
                    sa.Column("semantic_source", sa.String(), nullable=False), sa.Column("confidence", sa.Float()),
                    sa.Column("coordinates", sa.JSON()), sa.Column("geometry", sa.JSON()), sa.Column("properties", sa.JSON(), nullable=False),
                    sa.Column("search_text", sa.String(), nullable=False),
                    sa.Column("area_m2", sa.Float()), sa.Column("west", sa.Float()), sa.Column("south", sa.Float()),
                    sa.Column("east", sa.Float()), sa.Column("north", sa.Float()),
                    sa.ForeignKeyConstraint(["asset_id", "asset_version"], ["asset_versions.asset_id", "asset_versions.version"], ondelete="CASCADE"))
    for field in ("asset_id", "type", "west"):
        op.create_index("ix_spatial_objects_" + field, "spatial_objects", [field])
    op.create_index("ix_objects_asset_version", "spatial_objects", ["asset_id", "asset_version"])


def downgrade():
    op.drop_table("spatial_objects")
    op.drop_table("object_indexes")

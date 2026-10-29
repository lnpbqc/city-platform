"""Persist scene configurations, optimistic versions and fixed asset references."""
from alembic import op
import sqlalchemy as sa

revision = "0009_scenes"
down_revision = "0008_network_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("scenes", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("version", sa.Integer(), nullable=False),
                    sa.Column("document", sa.JSON(), nullable=False),
                    sa.Column("network_id", sa.String(120)), sa.Column("network_version", sa.String(32)),
                    sa.Column("created_at", sa.DateTime(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(), nullable=False),
                    sa.ForeignKeyConstraint(["network_id", "network_version"], ["network_versions.asset_id", "network_versions.version"]))
    op.create_table("scene_asset_references",
                    sa.Column("scene_id", sa.String(36), sa.ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("asset_id", sa.String(36), primary_key=True),
                    sa.Column("asset_version", sa.String(32), primary_key=True),
                    sa.ForeignKeyConstraint(["asset_id", "asset_version"], ["asset_versions.asset_id", "asset_versions.version"]))
    op.create_index("ix_scene_asset_references_asset", "scene_asset_references", ["asset_id", "asset_version"])


def downgrade():
    op.drop_table("scene_asset_references")
    op.drop_table("scenes")

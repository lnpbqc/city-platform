"""Preserve semantic GeoJSON independently of uploaded bytes."""
from alembic import op
import sqlalchemy as sa

revision = '0014_geojson_snapshot'
down_revision = '0013_object_rtree'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('spatial_objects', sa.Column('feature_members', sa.JSON(), nullable=True))
    op.add_column('spatial_objects', sa.Column('properties_null', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('geojson_snapshots',
        sa.Column('asset_id', sa.String(36), primary_key=True),
        sa.Column('asset_version', sa.String(32), primary_key=True),
        sa.Column('feature_count', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('validated', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['asset_id', 'asset_version'], ['asset_versions.asset_id', 'asset_versions.version'], ondelete='CASCADE'))
    op.create_table('geojson_members',
        sa.Column('asset_id', sa.String(36), primary_key=True),
        sa.Column('asset_version', sa.String(32), primary_key=True),
        sa.Column('ordinal', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['asset_id', 'asset_version'], ['geojson_snapshots.asset_id', 'geojson_snapshots.asset_version'], ondelete='CASCADE'))


def downgrade():
    op.drop_table('geojson_members')
    op.drop_table('geojson_snapshots')
    op.drop_column('spatial_objects', 'properties_null')
    op.drop_column('spatial_objects', 'feature_members')

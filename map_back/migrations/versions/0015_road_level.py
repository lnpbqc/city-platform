"""Persist the cumulative road display ceiling for each map layer."""
from alembic import op
import sqlalchemy as sa

revision = '0015_road_level'
down_revision = '0014_geojson_snapshot'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('layers', 'builtin_layer_states'):
        op.add_column(table, sa.Column('road_max_level', sa.Integer(), nullable=False, server_default='2'))


def downgrade():
    for table in ('builtin_layer_states', 'layers'):
        op.drop_column(table, 'road_max_level')

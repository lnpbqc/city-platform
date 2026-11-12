"""Durable derivative jobs, with orphan records retained until remote cleanup."""
from alembic import op
import sqlalchemy as sa

revision = '0016_render_jobs'
down_revision = '0015_road_level'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('render_jobs',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('asset_id', sa.String(80), nullable=False),
        sa.Column('version', sa.String(32), nullable=False),
        sa.Column('profile', sa.String(16), nullable=False),
        sa.Column('recipe', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('remote_id', sa.String(80)),
        sa.Column('stage', sa.String(500), nullable=False),
        sa.Column('error', sa.String(2000), nullable=False),
        sa.Column('manifest', sa.JSON), sa.Column('sha256', sa.String(64)),
        sa.Column('byte_size', sa.Integer, nullable=False), sa.Column('attempts', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False), sa.Column('updated_at', sa.DateTime, nullable=False),
        sa.Column('ready_at', sa.DateTime), sa.Column('source_expires_at', sa.DateTime),
        sa.Column('source_state', sa.String(16), nullable=False),
        sa.UniqueConstraint('asset_id', 'version', 'profile', 'recipe'))
    op.create_index('ix_render_jobs_asset_id', 'render_jobs', ['asset_id'])


def downgrade():
    op.drop_table('render_jobs')

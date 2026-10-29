"""Persist named locations and custom layer map state."""
from alembic import op
import sqlalchemy as sa

revision = "0003_bookmarks_map_state"
down_revision = "0002_assets"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("region_id", sa.String(80), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("layers") as batch:
        batch.add_column(sa.Column("map_attached", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("map_visible", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("map_opacity", sa.Float(), nullable=False, server_default="1"))


def downgrade():
    with op.batch_alter_table("layers") as batch:
        batch.drop_column("map_opacity")
        batch.drop_column("map_visible")
        batch.drop_column("map_attached")
    op.drop_table("bookmarks")

"""Track published file assets independently of layer registrations."""
from alembic import op
import sqlalchemy as sa

revision = "0002_assets"
down_revision = "0001_layers"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("original_name", sa.String(255), nullable=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("entry_url", sa.String(2048), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(1000), nullable=False),
    )
    with op.batch_alter_table("layers") as batch:
        batch.add_column(sa.Column("asset_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_layers_asset_id", "assets", ["asset_id"], ["id"])
        batch.create_index("ix_layers_asset_id", ["asset_id"])


def downgrade():
    with op.batch_alter_table("layers") as batch:
        batch.drop_index("ix_layers_asset_id")
        batch.drop_constraint("fk_layers_asset_id", type_="foreignkey")
        batch.drop_column("asset_id")
    op.drop_table("assets")

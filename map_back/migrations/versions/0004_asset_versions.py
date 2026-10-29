"""Version existing assets in place and distinguish protected defaults."""
from alembic import op
import sqlalchemy as sa

revision = "0004_asset_versions"
down_revision = "0003_bookmarks_map_state"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("current_version", sa.String(32), nullable=False, server_default="1.0.0"))
    op.add_column("assets", sa.Column("source_kind", sa.String(16), nullable=False, server_default="upload"))
    op.add_column("assets", sa.Column("protected", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "asset_versions",
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.String(32), primary_key=True),
        sa.Column("entry_url", sa.String(2048), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.execute("INSERT INTO asset_versions (asset_id,version,entry_url,byte_size,file_count,created_at) "
               "SELECT id,'1.0.0',entry_url,byte_size,file_count,COALESCE(uploaded_at,discovered_at) FROM assets")
    with op.batch_alter_table("layers") as batch:
        batch.add_column(sa.Column("asset_version", sa.String(32), nullable=True))
        batch.create_foreign_key("fk_layers_asset_version", "asset_versions", ["asset_id", "asset_version"], ["asset_id", "version"])
    op.execute("UPDATE layers SET asset_version='1.0.0' WHERE asset_id IS NOT NULL")
    op.execute("CREATE TRIGGER asset_version_immutable BEFORE UPDATE OF asset_id,version,entry_url,byte_size,file_count,created_at "
               "ON asset_versions BEGIN SELECT RAISE(ABORT, '资产版本不可修改'); END")


def downgrade():
    with op.batch_alter_table("layers") as batch:
        batch.drop_constraint("fk_layers_asset_version", type_="foreignkey")
        batch.drop_column("asset_version")
    op.drop_table("asset_versions")
    op.drop_column("assets", "protected")
    op.drop_column("assets", "source_kind")
    op.drop_column("assets", "current_version")

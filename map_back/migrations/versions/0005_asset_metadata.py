"""Store version fingerprints and external registration metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0005_asset_metadata"
down_revision = "0004_asset_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assets", sa.Column("name", sa.String(120), nullable=False, server_default=""))
    op.add_column("assets", sa.Column("source", sa.String(500), nullable=False, server_default=""))
    op.add_column("assets", sa.Column("coordinate_description", sa.String(1000), nullable=False, server_default=""))
    op.add_column("assets", sa.Column("registration_key", sa.String(2048), nullable=True))
    op.create_index("ix_assets_registration_key", "assets", ["registration_key"], unique=True)
    op.execute("UPDATE assets SET name=substr(COALESCE((SELECT name FROM layers WHERE layers.asset_id=assets.id "
               "ORDER BY created_at,id LIMIT 1),original_name,id),1,120), "
               "source=COALESCE((SELECT source FROM layers WHERE layers.asset_id=assets.id ORDER BY created_at,id LIMIT 1),'')")
    op.add_column("asset_versions", sa.Column("sha256", sa.String(64), nullable=True))
    op.add_column("asset_versions", sa.Column("file_manifest", sa.JSON(), nullable=True))
    op.add_column("asset_versions", sa.Column("bounds", sa.JSON(), nullable=True))
    op.execute("CREATE TRIGGER asset_fingerprint_immutable BEFORE UPDATE OF sha256,file_manifest,bounds ON asset_versions "
               "WHEN OLD.sha256 IS NOT NULL BEGIN SELECT RAISE(ABORT, '资产校验和不可修改'); END")


def downgrade():
    op.execute("DROP TRIGGER asset_fingerprint_immutable")
    op.drop_column("asset_versions", "bounds")
    op.drop_column("asset_versions", "file_manifest")
    op.drop_column("asset_versions", "sha256")
    op.drop_index("ix_assets_registration_key", table_name="assets")
    for column in ("registration_key", "coordinate_description", "source", "name"):
        op.drop_column("assets", column)

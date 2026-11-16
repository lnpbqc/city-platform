"""Track in-place revisions for local 3D Tiles assets."""
from alembic import context, op
import sqlalchemy as sa

revision = "0021_tiles_working_asset"
down_revision = "0020_tiles_calibration"
branch_labels = None
depends_on = None


def _triggers(working: bool):
    current_local = ("""EXISTS(SELECT 1 FROM assets WHERE id=OLD.asset_id AND type='3dtiles'
        AND source_kind='upload' AND protected=0 AND current_version=OLD.version
        AND OLD.entry_url LIKE '/data-files/%')""" if working else "0")
    op.execute(f"""CREATE TRIGGER asset_version_immutable BEFORE UPDATE OF
        asset_id,version,entry_url,byte_size,file_count,created_at ON asset_versions
        WHEN NEW.asset_id<>OLD.asset_id OR NEW.version<>OLD.version OR NEW.entry_url IS NOT OLD.entry_url
          OR NEW.created_at<>OLD.created_at OR NOT ({current_local})
        BEGIN SELECT RAISE(ABORT, '资产版本不可修改'); END""")
    op.execute(f"""CREATE TRIGGER asset_fingerprint_immutable BEFORE UPDATE OF sha256,file_manifest,bounds ON asset_versions
        WHEN OLD.sha256 IS NOT NULL AND NOT ({current_local}) BEGIN SELECT RAISE(ABORT, '资产校验和不可修改'); END""")
    op.execute(f"""CREATE TRIGGER asset_calibration_immutable BEFORE UPDATE OF tiles_calibrated{',revision,tiles_terrain_anchor' if working else ''}
        ON asset_versions WHEN NOT ({current_local}) BEGIN SELECT RAISE(ABORT, '资产校准状态不可修改'); END""")


def _drop_triggers():
    for name in ("asset_version_immutable", "asset_fingerprint_immutable", "asset_calibration_immutable"):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")


def upgrade():
    existing = set() if context.is_offline_mode() else {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("asset_versions")
    }
    _drop_triggers()
    if "revision" not in existing:
        op.add_column("asset_versions", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    if "tiles_terrain_anchor" not in existing:
        op.add_column("asset_versions", sa.Column("tiles_terrain_anchor", sa.JSON(), nullable=True))
    _triggers(True)


def downgrade():
    _drop_triggers()
    op.drop_column("asset_versions", "tiles_terrain_anchor")
    op.drop_column("asset_versions", "revision")
    _triggers(False)

"""Allow updating the current model of assets published with a legacy tiles URL."""
from alembic import op

revision = "0022_legacy_working_tiles"
down_revision = "0021_tiles_working_asset"
branch_labels = None
depends_on = None


def _replace(legacy: bool):
    local = "OLD.entry_url LIKE '/data-files/%'"
    if legacy:
        legacy_prefix = "'/api/assets/' || OLD.asset_id || '/versions/' || OLD.version || '/tiles/'"
        local += f""" OR (OLD.tiles_calibrated=1 AND
            substr(OLD.entry_url, 1, length({legacy_prefix})) = ({legacy_prefix}))"""
    current = f"""EXISTS(SELECT 1 FROM assets WHERE id=OLD.asset_id AND type='3dtiles'
        AND source_kind='upload' AND protected=0 AND current_version=OLD.version AND ({local}))"""
    triggers = {
        "asset_version_immutable": (
            "asset_id,version,entry_url,byte_size,file_count,created_at",
            f"""NEW.asset_id<>OLD.asset_id OR NEW.version<>OLD.version OR NEW.entry_url IS NOT OLD.entry_url
                OR NEW.created_at<>OLD.created_at OR NOT ({current})""",
            "资产版本不可修改",
        ),
        "asset_fingerprint_immutable": (
            "sha256,file_manifest,bounds", f"OLD.sha256 IS NOT NULL AND NOT ({current})", "资产校验和不可修改",
        ),
        "asset_calibration_immutable": (
            "tiles_calibrated,revision,tiles_terrain_anchor", f"NOT ({current})", "资产校准状态不可修改",
        ),
    }
    for name, (columns, predicate, message) in triggers.items():
        op.execute(f"DROP TRIGGER {name}")
        op.execute(f"""CREATE TRIGGER {name} BEFORE UPDATE OF {columns} ON asset_versions
            WHEN {predicate} BEGIN SELECT RAISE(ABORT, '{message}'); END""")


def upgrade():
    _replace(True)


def downgrade():
    _replace(False)

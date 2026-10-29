"""Durable runs, immutable snapshots and historical asset references."""
from alembic import op
import sqlalchemy as sa

revision = "0010_runs"
down_revision = "0009_scenes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("runs", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("inputs_sha256", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(80), nullable=False), sa.Column("data_version", sa.String(160), nullable=False),
        sa.Column("scene_id", sa.String(36), nullable=False), sa.Column("scene_version", sa.Integer(), nullable=False),
        sa.Column("network_id", sa.String(120), nullable=False), sa.Column("network_version", sa.String(32), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False), sa.Column("idempotency_key", sa.String(200), unique=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=False), sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()), sa.Column("elapsed_ms", sa.Float()),
        sa.Column("result", sa.JSON()), sa.Column("error", sa.JSON()),
        sa.Column("trace_id", sa.String(32), nullable=False), sa.Column("log_text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["network_id", "network_version"], ["network_versions.asset_id", "network_versions.version"]),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')", name="ck_run_status"),
        sa.CheckConstraint("status NOT IN ('succeeded','failed','cancelled') OR finished_at IS NOT NULL", name="ck_run_finished"),
        sa.CheckConstraint("status != 'running' OR started_at IS NOT NULL", name="ck_run_started"))
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_scene_id", "runs", ["scene_id"])
    op.create_table("run_asset_references",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("asset_id", sa.String(36), primary_key=True), sa.Column("asset_version", sa.String(32), primary_key=True),
        sa.ForeignKeyConstraint(["asset_id", "asset_version"], ["asset_versions.asset_id", "asset_versions.version"]))
    op.create_index("ix_run_asset_references_asset", "run_asset_references", ["asset_id", "asset_version"])
    op.execute("CREATE TRIGGER run_input_immutable BEFORE UPDATE OF id,inputs_sha256,model_version,data_version,scene_id,scene_version,"
               "network_id,network_version,input_snapshot,idempotency_key,submitted_at,trace_id ON runs "
               "BEGIN SELECT RAISE(ABORT, '运行输入不可修改'); END")
    op.execute("CREATE TRIGGER run_terminal_immutable BEFORE UPDATE ON runs "
               "WHEN OLD.status IN ('succeeded','failed','cancelled') BEGIN SELECT RAISE(ABORT, '终态运行不可修改'); END")
    op.execute("CREATE TRIGGER run_state_machine BEFORE UPDATE OF status ON runs WHEN NEW.status != OLD.status AND NOT "
               "((OLD.status='queued' AND NEW.status IN ('running','cancelled')) OR "
               "(OLD.status='running' AND NEW.status IN ('succeeded','failed','cancelled'))) "
               "BEGIN SELECT RAISE(ABORT, '运行状态转换无效'); END")


def downgrade():
    op.execute("UPDATE scenes SET document = json_set(document, '$.run_id', NULL) "
               "WHERE json_extract(document, '$.run_id') IN (SELECT id FROM runs)")
    op.drop_table("run_asset_references")
    op.drop_table("runs")

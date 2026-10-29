"""Store immutable network documents by identity and version."""
from alembic import op
import sqlalchemy as sa

revision = "0008_network_versions"
down_revision = "0007_object_index"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("network_versions",
                    sa.Column("asset_id", sa.String(120), primary_key=True),
                    sa.Column("version", sa.String(32), primary_key=True),
                    sa.Column("document", sa.JSON(), nullable=False),
                    sa.Column("created_at", sa.DateTime(), nullable=False))
    op.execute("CREATE TRIGGER network_version_immutable BEFORE UPDATE ON network_versions "
               "BEGIN SELECT RAISE(ABORT, '路网版本不可修改'); END")


def downgrade():
    op.drop_table("network_versions")

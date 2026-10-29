"""Keep workspace bookmarks alongside existing region and point bookmarks."""
from alembic import op
import sqlalchemy as sa

revision = "0012_workspace_bookmarks"
down_revision = "0011_timeseries"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bookmarks", sa.Column("state", sa.JSON(), nullable=True))


def downgrade():
    op.execute("DELETE FROM bookmarks WHERE kind='scene'")
    with op.batch_alter_table("bookmarks") as batch:
        batch.drop_column("state")

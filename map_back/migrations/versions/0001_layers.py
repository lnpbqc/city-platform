"""Create the layer catalog."""
from alembic import op
import sqlalchemy as sa

revision = "0001_layers"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "layers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("source", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("layers")

"""Store project display regions and seed the four existing shortcuts."""
import json

import sqlalchemy as sa
from alembic import context, op

revision = "0019_display_regions"
down_revision = "0018_tiles_terrain_alignment"
branch_labels = None
depends_on = None


def upgrade():
    regions = op.create_table(
        "display_regions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("camera", sa.JSON(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("radius_m", sa.Float(), nullable=False),
    )
    # Camera poses are the end positions of the original Cesium region shortcuts.
    initial = [
        ("demo-victoria-harbour", "香港维港", 114.1705, 22.2935, 5000, 22.2542524344, 4831.9310, -0.838441253),
        ("demo-zhujiang-new-town", "广州珠江新城", 113.3235, 23.119, 4000, 23.0918250646, 3344.8658, -0.838231059),
        ("demo-university-town", "大学城校区", 113.366746, 23.043612, 2000, 23.0308292736, 1812.5827, -0.907793623),
        ("demo-huangpu", "黄埔校区", 113.570902, 23.310314, 2000, 23.3014211988, 1260.8937, -0.907725936),
    ]
    rows = []
    for key, name, lon, lat, radius, camera_lat, height, pitch in initial:
        camera = {"longitude": lon, "latitude": camera_lat, "height": height, "heading": 0,
                  "pitch": pitch, "roll": 0, "scene_mode": "3d"}
        rows.append({"id": key, "name": name, "longitude": lon, "latitude": lat,
                     "radius_m": radius, "camera": camera})
    offline = context.is_offline_mode()
    if offline:
        for row in rows:
            row["camera"] = op.inline_literal(json.dumps(row["camera"]), type_=sa.String())
    op.bulk_insert(regions, rows, multiinsert=not offline)


def downgrade():
    op.drop_table("display_regions")

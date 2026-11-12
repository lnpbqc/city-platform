from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from .assets import Asset

class Layer(Base):
    __tablename__ = "layers"
    __table_args__ = (ForeignKeyConstraint(["asset_id", "asset_version"],
                      ["asset_versions.asset_id", "asset_versions.version"], name="fk_layers_asset_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(16))
    url: Mapped[str] = mapped_column(String(2048))
    source: Mapped[str] = mapped_column(String(500), default="")
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"), index=True)
    asset_version: Mapped[str | None] = mapped_column(String(32))
    asset: Mapped[Asset | None] = relationship(foreign_keys=[asset_id], viewonly=True)
    map_attached: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    map_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    map_opacity: Mapped[float] = mapped_column(Float, default=1, server_default="1")
    road_max_level: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    tiles_height_offset_m: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    tiles_ground_anchor: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    tiles_align_to_terrain: Mapped[bool | None] = mapped_column(Boolean)
    map_order: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    orderable: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def asset_source_kind(self):
        return self.asset.source_kind if self.asset else None


class BuiltinLayerState(Base):
    __tablename__ = "builtin_layer_states"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    map_attached: Mapped[bool] = mapped_column(Boolean, default=True)
    map_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    map_opacity: Mapped[float] = mapped_column(Float, default=1)
    road_max_level: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    tiles_placements: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    map_order: Mapped[int] = mapped_column(Integer)

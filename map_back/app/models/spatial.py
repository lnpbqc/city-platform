from sqlalchemy import Boolean, Float, ForeignKeyConstraint, Integer, JSON, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class ObjectIndex(Base):
    __tablename__ = "object_indexes"
    __table_args__ = (ForeignKeyConstraint(["asset_id", "asset_version"], ["asset_versions.asset_id", "asset_versions.version"], ondelete="CASCADE"),)

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str] = mapped_column(String(1000), default="")


class SpatialObject(Base):
    __tablename__ = "spatial_objects"
    __table_args__ = (ForeignKeyConstraint(["asset_id", "asset_version"], ["asset_versions.asset_id", "asset_versions.version"], ondelete="CASCADE"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(36), index=True)
    asset_version: Mapped[str] = mapped_column(String(32))
    feature_index: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str | None] = mapped_column(String)
    height_m: Mapped[float | None] = mapped_column(Float)
    level: Mapped[str | None] = mapped_column(String)
    semantic_source: Mapped[str] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    coordinates: Mapped[list | None] = mapped_column(JSON)
    geometry: Mapped[dict | None] = mapped_column(JSON)
    properties: Mapped[dict] = mapped_column(JSON)
    feature_members: Mapped[dict | None] = mapped_column(JSON)
    properties_null: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    search_text: Mapped[str] = mapped_column(String)
    area_m2: Mapped[float | None] = mapped_column(Float)
    west: Mapped[float | None] = mapped_column(Float, index=True)
    south: Mapped[float | None] = mapped_column(Float)
    east: Mapped[float | None] = mapped_column(Float)
    north: Mapped[float | None] = mapped_column(Float)

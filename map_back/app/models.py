from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    original_name: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(16))
    entry_url: Mapped[str | None] = mapped_column(String(2048))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(16), default="active")
    error: Mapped[str] = mapped_column(String(1000), default="")
    current_version: Mapped[str] = mapped_column(String(32), default="1.0.0", server_default="1.0.0")
    source_kind: Mapped[str] = mapped_column(String(16), default="upload", server_default="upload")
    protected: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    source: Mapped[str] = mapped_column(String(500), default="", server_default="")
    coordinate_description: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    registration_key: Mapped[str | None] = mapped_column(String(2048), index=True, unique=True)


class AssetVersion(Base):
    __tablename__ = "asset_versions"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    entry_url: Mapped[str | None] = mapped_column(String(2048))
    byte_size: Mapped[int] = mapped_column(Integer)
    file_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    sha256: Mapped[str | None] = mapped_column(String(64))
    file_manifest: Mapped[list[dict] | None] = mapped_column(JSON)
    bounds: Mapped[dict | None] = mapped_column(JSON)


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
    map_order: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    orderable: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def asset_source_kind(self):
        return self.asset.source_kind if self.asset else None


class Bookmark(Base):
    __tablename__ = "bookmarks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    region_id: Mapped[str | None] = mapped_column(String(80))
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    state: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))


class BuiltinLayerState(Base):
    __tablename__ = "builtin_layer_states"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    map_attached: Mapped[bool] = mapped_column(Boolean, default=True)
    map_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    map_opacity: Mapped[float] = mapped_column(Float, default=1)
    map_order: Mapped[int] = mapped_column(Integer)


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
    search_text: Mapped[str] = mapped_column(String)
    area_m2: Mapped[float | None] = mapped_column(Float)
    west: Mapped[float | None] = mapped_column(Float, index=True)
    south: Mapped[float | None] = mapped_column(Float)
    east: Mapped[float | None] = mapped_column(Float)
    north: Mapped[float | None] = mapped_column(Float)


class TimeSeriesSnapshot(Base):
    __tablename__ = "time_series_snapshots"
    __table_args__ = (ForeignKeyConstraint(["asset_id", "asset_version"],
                      ["asset_versions.asset_id", "asset_versions.version"], ondelete="CASCADE"),)

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    unit: Mapped[str] = mapped_column(String(32))
    document: Mapped[dict] = mapped_column(JSON)


class NetworkVersion(Base):
    __tablename__ = "network_versions"

    asset_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    document: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (ForeignKeyConstraint(["network_id", "network_version"],
                       ["network_versions.asset_id", "network_versions.version"]),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSON)
    network_id: Mapped[str | None] = mapped_column(String(120))
    network_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class SceneAssetReference(Base):
    __tablename__ = "scene_asset_references"
    __table_args__ = (ForeignKeyConstraint(["asset_id", "asset_version"],
                       ["asset_versions.asset_id", "asset_versions.version"]),)

    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_version: Mapped[str] = mapped_column(String(32), primary_key=True)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (ForeignKeyConstraint(["network_id", "network_version"],
                       ["network_versions.asset_id", "network_versions.version"]),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    inputs_sha256: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(80))
    data_version: Mapped[str] = mapped_column(String(160))
    scene_id: Mapped[str] = mapped_column(String(36), index=True)
    scene_version: Mapped[int] = mapped_column(Integer)
    network_id: Mapped[str] = mapped_column(String(120))
    network_version: Mapped[str] = mapped_column(String(32))
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    elapsed_ms: Mapped[float | None] = mapped_column(Float)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(32))
    log_text: Mapped[str] = mapped_column(Text)


class RunAssetReference(Base):
    __tablename__ = "run_asset_references"
    __table_args__ = (ForeignKeyConstraint(["asset_id", "asset_version"],
                       ["asset_versions.asset_id", "asset_versions.version"]),)

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_version: Mapped[str] = mapped_column(String(32), primary_key=True)

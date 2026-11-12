from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

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

"""Display derivatives are separate from immutable source asset metadata."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class RenderJob(Base):
    __tablename__ = 'render_jobs'
    __table_args__ = (UniqueConstraint('asset_id', 'version', 'profile', 'recipe'),)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(32))
    profile: Mapped[str] = mapped_column(String(16))
    recipe: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default='queued')
    remote_id: Mapped[str | None] = mapped_column(String(80))
    stage: Mapped[str] = mapped_column(String(500), default='等待切片服务')
    error: Mapped[str] = mapped_column(String(2000), default='')
    manifest: Mapped[dict | None] = mapped_column(JSON)
    sha256: Mapped[str | None] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_state: Mapped[str] = mapped_column(String(16), default='retained')

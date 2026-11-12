from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

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

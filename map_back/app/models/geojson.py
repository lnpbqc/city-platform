from sqlalchemy import Boolean, ForeignKeyConstraint, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class GeoJSONSnapshot(Base):
    __tablename__ = "geojson_snapshots"
    __table_args__ = (ForeignKeyConstraint(["asset_id", "asset_version"], ["asset_versions.asset_id", "asset_versions.version"], ondelete="CASCADE"),)

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    feature_count: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    validated: Mapped[bool] = mapped_column(Boolean, default=False)


class GeoJSONMember(Base):
    __tablename__ = "geojson_members"
    __table_args__ = (ForeignKeyConstraint(["asset_id", "asset_version"], ["geojson_snapshots.asset_id", "geojson_snapshots.asset_version"], ondelete="CASCADE"),)

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    value: Mapped[object] = mapped_column(JSON)

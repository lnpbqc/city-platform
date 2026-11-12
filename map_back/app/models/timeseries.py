from sqlalchemy import ForeignKeyConstraint, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class TimeSeriesSnapshot(Base):
    __tablename__ = "time_series_snapshots"
    __table_args__ = (ForeignKeyConstraint(["asset_id", "asset_version"],
                      ["asset_versions.asset_id", "asset_versions.version"], ondelete="CASCADE"),)

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    unit: Mapped[str] = mapped_column(String(32))
    document: Mapped[dict] = mapped_column(JSON)

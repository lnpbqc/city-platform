from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

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

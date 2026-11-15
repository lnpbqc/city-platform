from sqlalchemy import Float, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DisplayRegion(Base):
    __tablename__ = "display_regions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    camera: Mapped[dict] = mapped_column(JSON)
    longitude: Mapped[float] = mapped_column(Float)
    latitude: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float)

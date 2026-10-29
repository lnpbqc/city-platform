import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

STORAGE_DIR = Path(os.environ.get("MAP_STORAGE_DIR", Path(__file__).resolve().parents[1] / "storage"))
FILES_DIR = STORAGE_DIR / "files"
FILES_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.environ.get("MAP_DATABASE_URL", f"sqlite:///{(STORAGE_DIR / 'catalog.db').as_posix()}")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(engine)


class Base(DeclarativeBase):
    pass


def get_session():
    with SessionLocal() as session:
        yield session

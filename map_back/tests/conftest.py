import os
import shutil
import tempfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

_storage = tempfile.TemporaryDirectory(prefix="city-map-tests-")
os.environ["MAP_STORAGE_DIR"] = _storage.name
os.environ.pop("MAP_DATABASE_URL", None)

from app.database import FILES_DIR, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Asset, Bookmark, BuiltinLayerState, Layer, Run, Scene  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    _storage.cleanup()


@pytest.fixture
def client():
    assert FILES_DIR.resolve().is_relative_to(Path(_storage.name).resolve())
    shutil.rmtree(FILES_DIR)
    FILES_DIR.mkdir()
    runs_dir = Path(_storage.name) / "runs"
    if runs_dir.exists():
        shutil.rmtree(runs_dir)
    with TestClient(app) as test_client:
        with SessionLocal() as session:
            session.query(Run).delete()
            session.query(Scene).delete()
            session.query(BuiltinLayerState).delete()
            session.query(Asset).delete()
            session.commit()
        yield test_client
    with SessionLocal() as session:
        session.query(Run).delete()
        session.query(Scene).delete()
        session.query(Bookmark).delete()
        session.query(Layer).delete()
        session.query(BuiltinLayerState).delete()
        session.query(Asset).delete()
        session.commit()

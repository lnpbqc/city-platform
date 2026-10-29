import os
from pathlib import Path
import subprocess
import sys


def test_timeseries_migration_with_existing_assets_scenes_runs_and_nonempty_snapshots(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    storage = tmp_path / "time-migration-storage"
    environment = {**os.environ, "MAP_STORAGE_DIR": str(storage),
                   "MAP_DATABASE_URL": "sqlite:///" + (storage / "catalog.db").as_posix(),
                   "PYTHONIOENCODING": "utf-8"}
    script = r'''
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

sys.path.insert(0, str(Path("tests").resolve()))
from app.builtin_assets import SAMPLES_DIR
from app.database import DATABASE_URL, FILES_DIR, SessionLocal, engine
from app.main import app
from app.models import TimeSeriesSnapshot
from app.networks import ensure_networks
from app.run_worker import RunQueue
from test_scenes import draft, layer_state, upload


def rows():
    with sqlite3.connect(DATABASE_URL.removeprefix("sqlite:///")) as connection:
        tables = [name for name, in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','time_series_snapshots')")]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        result = {}
        for table in tables:
            columns = [row[1] for row in connection.execute('PRAGMA table_info("' + table + '")')
                       if not (table == "bookmarks" and row[1] == "state")]
            fields = ','.join('"' + column + '"' for column in columns)
            result[table] = sorted(connection.execute('SELECT ' + fields + ' FROM "' + table + '"').fetchall(), key=repr)
        return result


def fingerprints(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


try:
    config = Config(str(Path("alembic.ini").resolve()))
    command.upgrade(config, "0010_runs")
    with SessionLocal() as session:
        ensure_networks(session)
        session.commit()
    # No context manager: prepare genuine 0010 data without invoking the new lifespan.
    client = TestClient(app)
    try:
        layer_response = upload(client)
        assert layer_response.status_code == 201, layer_response.text
        layer = layer_response.json()
        scene_response = client.post("/api/scenes", json={**draft(), "layers": [layer_state(layer)]})
        assert scene_response.status_code == 201, scene_response.text
        scene = scene_response.json()
        run_response = client.post("/api/runs", json={"scene_id": scene["id"], "network": scene["network"],
                                   "origin": "S", "destination": "T", "blocked_edges": []})
        assert run_response.status_code == 201, run_response.text
        run = run_response.json()
        with sqlite3.connect(DATABASE_URL.removeprefix("sqlite:///")) as connection:
            connection.execute("INSERT INTO bookmarks (id,name,kind,region_id,created_at) VALUES (?,?,?,?,?)",
                               ("legacy-region", "迁移收藏", "region", "guangzhou", "2026-10-20 00:00:00"))
    finally:
        client.close()
    before = rows()
    files_before = fingerprints(FILES_DIR)
    samples_before = fingerprints(SAMPLES_DIR)
    command.upgrade(config, "head")
    assert rows() == before, "0011升级仅增加时序表，不改旧资产、对象、场景或运行"
    with patch.object(RunQueue, "_loop", lambda self: self._stop.wait()):
        with TestClient(app) as client:
            assert client.get(f"/api/scenes/{scene['id']}").json() == scene
            assert client.get(f"/api/runs/{run['run_id']}").json() == run
            assert client.get(f"/api/layers/{layer['id']}/times").json() == []
            assert len(client.get("/api/layers/demo-points/times").json()) == 4
            with SessionLocal() as session:
                assert len(list(session.scalars(select(TimeSeriesSnapshot)))) == 6
                session.add(TimeSeriesSnapshot(asset_id=layer["asset_id"], asset_version="1.0.0", unit="cm",
                            document={"2026-10-25T00:00:00Z": {}}))
                session.commit()
        before_downgrade = rows()
        command.downgrade(config, "0010_runs")
        assert rows() == before_downgrade, "带非空时序下迁只移除时序，其他数据保持"
        with sqlite3.connect(DATABASE_URL.removeprefix("sqlite:///")) as connection:
            assert connection.execute("SELECT name FROM sqlite_master WHERE name='time_series_snapshots'").fetchall() == []
            assert connection.execute("SELECT name FROM sqlite_master WHERE name='time_series_immutable'").fetchall() == []
        command.upgrade(config, "head")
        assert rows() == before_downgrade
        with TestClient(app) as client:
            assert client.get(f"/api/runs/{run['run_id']}/input").status_code == 200
            assert len(client.get("/api/layers/demo-points/times").json()) == 4
            with SessionLocal() as session:
                assert len(list(session.scalars(select(TimeSeriesSnapshot)))) == 6
        assert rows() == before_downgrade
    assert fingerprints(FILES_DIR) == files_before
    assert fingerprints(SAMPLES_DIR) == samples_before
finally:
    engine.dispose()
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=backend, env=environment,
                            capture_output=True, timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace")

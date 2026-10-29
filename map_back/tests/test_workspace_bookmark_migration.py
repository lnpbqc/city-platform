import os
from pathlib import Path
import subprocess
import sys


def test_workspace_bookmark_migration_preserves_old_records_and_only_removes_scene_bookmarks(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    storage = tmp_path / "workspace-bookmark-migration"
    environment = {**os.environ, "MAP_STORAGE_DIR": str(storage),
                   "MAP_DATABASE_URL": "sqlite:///" + (storage / "catalog.db").as_posix(), "PYTHONIOENCODING": "utf-8"}
    script = r'''
import hashlib
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("tests").resolve()))
from app.builtin_assets import SAMPLES_DIR
from app.database import DATABASE_URL, FILES_DIR, SessionLocal, engine
from app.main import app
from app.networks import ensure_networks
from app.run_worker import RunQueue
from test_scenes import draft, layer_state, upload
from test_workspace_bookmarks import workspace

database = DATABASE_URL.removeprefix("sqlite:///")
columns = "id,name,kind,region_id,longitude,latitude,created_at"


def core():
    with sqlite3.connect(database) as connection:
        tables = [name for name, in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('bookmarks','alembic_version')")]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        return {table: sorted(connection.execute('SELECT * FROM "' + table + '"').fetchall(), key=repr) for table in tables}


def bookmarks():
    with sqlite3.connect(database) as connection:
        return connection.execute("SELECT " + columns + " FROM bookmarks WHERE kind!='scene' ORDER BY id").fetchall()


def fingerprints(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


try:
    config = Config(str(Path("alembic.ini").resolve()))
    command.upgrade(config, "0011_timeseries")
    with SessionLocal() as session:
        ensure_networks(session)
        session.commit()
    with sqlite3.connect(database) as connection:
        connection.executemany("INSERT INTO bookmarks (" + columns + ") VALUES (?,?,?,?,?,?,?)", [
            ("old-region", "旧地区", "region", "440100", None, None, "2026-10-20 00:00:00"),
            ("old-point", "旧点位", "point", None, 113.3, 23.1, "2026-10-21 00:00:00")])
    client = TestClient(app)
    try:
        layer_response = upload(client)
        assert layer_response.status_code == 201, layer_response.text
        layer = layer_response.json()
        scene_response = client.post("/api/scenes", json={**draft(), "layers": [layer_state(layer)]})
        assert scene_response.status_code == 201, scene_response.text
        scene = scene_response.json()
        created = client.post("/api/runs", json={"scene_id": scene["id"], "network": scene["network"], "origin": "S", "destination": "T", "blocked_edges": []})
        assert created.status_code == 201, created.text
        run = created.json()
    finally:
        client.close()
    before_core, before_bookmarks = core(), bookmarks()
    files_before, samples_before = fingerprints(FILES_DIR), fingerprints(SAMPLES_DIR)
    command.upgrade(config, "head")
    assert core() == before_core and bookmarks() == before_bookmarks
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id,state FROM bookmarks ORDER BY id").fetchall() == [("old-point", None), ("old-region", None)]
    with patch.object(RunQueue, "_loop", lambda self: self._stop.wait()):
        with TestClient(app) as client:
            assert all(item["state"] is None for item in client.get("/api/bookmarks").json())
            captured = client.post("/api/scenes", json={**draft(), "layers": [layer_state(layer)], "run_id": run["run_id"]}).json()
            created = client.post("/api/bookmarks", json={"name": "新工作区", "kind": "scene", "state": workspace(captured)})
            assert created.status_code == 201, created.text
            workspace_id = created.json()["id"]
            assert client.post("/api/bookmarks", json={"name": "升级后新增地区", "kind": "region", "region_id": "440100"}).status_code == 201
            assert client.patch("/api/bookmarks/old-region", json={"name": "旧地区改名"}).status_code == 200
        expected_core, expected_bookmarks = core(), bookmarks()
        command.downgrade(config, "0011_timeseries")
        assert core() == expected_core and bookmarks() == expected_bookmarks
        with sqlite3.connect(database) as connection:
            assert "state" not in {row[1] for row in connection.execute("PRAGMA table_info(bookmarks)")}
            assert connection.execute("SELECT id FROM bookmarks WHERE id=?", (workspace_id,)).fetchall() == []
            assert connection.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0] == 3
        command.upgrade(config, "head")
        assert core() == expected_core and bookmarks() == expected_bookmarks
        with TestClient(app) as client:
            items = client.get("/api/bookmarks").json()
            assert len(items) == 3 and all(item["state"] is None for item in items)
            assert client.get(f"/api/scenes/{captured['id']}", params={"version": captured["version"]}).json() == captured
            assert client.get(f"/api/runs/{run['run_id']}").json() == run
            recreated = client.post("/api/bookmarks", json={"name": "再升级后工作区", "kind": "scene", "state": workspace(captured)})
            assert recreated.status_code == 201, recreated.text
        assert core() == expected_core
    assert fingerprints(FILES_DIR) == files_before and fingerprints(SAMPLES_DIR) == samples_before
finally:
    engine.dispose()
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=backend, env=environment,
                            capture_output=True, timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace")

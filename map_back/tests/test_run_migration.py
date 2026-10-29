import os
from pathlib import Path
import subprocess
import sys


def test_run_downgrade_clears_only_removed_run_links_and_scene_remains_runnable(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    storage = tmp_path / "run-migration-storage"
    environment = {**os.environ, "MAP_STORAGE_DIR": str(storage),
                   "MAP_DATABASE_URL": "sqlite:///" + (storage / "catalog.db").as_posix(),
                   "PYTHONIOENCODING": "utf-8"}
    script = r'''
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("tests").resolve()))
from app.database import DATABASE_URL, engine
from app.main import app
from app.run_worker import RunQueue
from test_scenes import draft, layer_state, upload


def scene_rows():
    with sqlite3.connect(DATABASE_URL.removeprefix("sqlite:///")) as connection:
        rows = connection.execute("SELECT id,version,document,network_id,network_version,created_at,updated_at FROM scenes ORDER BY id").fetchall()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    return [(row[0], row[1], json.loads(row[2]), *row[3:]) for row in rows]


try:
    config = Config(str(Path("alembic.ini").resolve()))
    command.upgrade(config, "head")
    with patch.object(RunQueue, "_loop", lambda self: self._stop.wait()):
        with TestClient(app) as client:
            layer = upload(client).json()
            scene_body = {**draft(), "layers": [layer_state(layer)]}
            scene_response = client.post("/api/scenes", json=scene_body)
            assert scene_response.status_code == 201, scene_response.text
            scene = scene_response.json()
            request = {"scene_id": scene["id"], "network": scene_body["network"],
                       "origin": "S", "destination": "T", "blocked_edges": ["B-T"]}
            created = client.post("/api/runs", json=request)
            assert created.status_code == 201, created.text
            old_run_id = created.json()["run_id"]
            linked = client.put(f"/api/scenes/{scene['id']}", json={**scene_body, "run_id": old_run_id}, headers={"If-Match": '"1"'})
            assert linked.status_code == 200, linked.text
            unlinked = client.post("/api/scenes", json={**draft(), "name": "无运行关联"})
            assert unlinked.status_code == 201, unlinked.text
            expected_scene = {**linked.json(), "run_id": None}
        before = scene_rows()
        expected_rows = [(identity, version, {**document, "run_id": None} if document.get("run_id") == old_run_id else document, *other)
                         for identity, version, document, *other in before]
        command.downgrade(config, "0009_scenes")
        assert scene_rows() == expected_rows, "降级须只清理已移除运行的run_id，保留其它字段、版本和时间"
        command.upgrade(config, "head")
        assert scene_rows() == expected_rows
        with TestClient(app) as client:
            fetched = client.get(f"/api/scenes/{scene['id']}")
            assert fetched.status_code == 200 and fetched.json() == expected_scene, fetched.text
            fresh = client.post("/api/runs", json=request)
            assert fresh.status_code == 201, fresh.text
            assert fresh.json()["run_id"] != old_run_id
            assert fresh.json()["scene_version"] == expected_scene["version"]
finally:
    engine.dispose()
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=backend, env=environment,
                            capture_output=True, timeout=45,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace")

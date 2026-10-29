import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timedelta
from uuid import UUID

import pytest

from app.database import STORAGE_DIR


def register(client):
    response = client.post("/api/layers", json={"name": "测试图层", "type": "geojson", "url": "https://example.invalid/a.geojson"})
    assert response.status_code == 201, response.text
    return response.json()


def test_bookmark_crud_order_and_utc(client):
    region = client.post("/api/bookmarks", json={"name": "  广州  ", "kind": "region", "region_id": "440100"})
    assert region.status_code == 201, region.text
    region = region.json()
    assert region["name"] == "广州" and region["region_id"] == "440100"
    assert region["longitude"] is None and region["latitude"] is None
    assert str(UUID(region["id"])) == region["id"]
    assert datetime.fromisoformat(region["created_at"]).utcoffset() == timedelta(0)
    point = client.post("/api/bookmarks", json={"name": "点位", "kind": "point", "longitude": 113.315959, "latitude": 23.121995})
    assert point.status_code == 201, point.text
    point = point.json()
    assert point["region_id"] is None
    assert [record["id"] for record in client.get("/api/bookmarks").json()] == [point["id"], region["id"]]
    renamed = client.patch(f"/api/bookmarks/{region['id']}", json={"name": "  广州市  "})
    assert renamed.status_code == 200 and renamed.json()["name"] == "广州市"
    assert renamed.json()["created_at"] == region["created_at"]
    assert client.delete(f"/api/bookmarks/{region['id']}").status_code == 204
    assert [record["id"] for record in client.get("/api/bookmarks").json()] == [point["id"]]
    assert client.delete(f"/api/bookmarks/{region['id']}").status_code == 404
    assert client.patch(f"/api/bookmarks/{region['id']}", json={"name": "不存在"}).status_code == 404


@pytest.mark.parametrize("body", [
    {"name": "", "kind": "region", "region_id": "440100"},
    {"name": "  ", "kind": "region", "region_id": "440100"},
    {"name": "x" * 121, "kind": "region", "region_id": "440100"},
    {"name": "地区", "kind": "region"},
    {"name": "地区", "kind": "region", "region_id": " "},
    {"name": "地区", "kind": "region", "region_id": "440100", "longitude": 1},
    {"name": "点位", "kind": "point", "longitude": 0},
    {"name": "点位", "kind": "point", "longitude": 0, "latitude": 0, "region_id": "440100"},
    {"name": "点位", "kind": "point", "longitude": 181, "latitude": 0},
    {"name": "点位", "kind": "point", "longitude": -181, "latitude": 0},
    {"name": "点位", "kind": "point", "longitude": 0, "latitude": 91},
    {"name": "点位", "kind": "point", "longitude": 0, "latitude": -91},
    {"name": "点位", "kind": "point", "longitude": "NaN", "latitude": 0},
    {"name": "点位", "kind": "point", "longitude": 0, "latitude": "Infinity"},
    {"name": "其他", "kind": "camera"},
])
def test_invalid_bookmark_inputs(client, body):
    assert client.post("/api/bookmarks", json=body).status_code == 422
    assert client.get("/api/bookmarks").json() == []


def test_bookmark_rename_only_and_coordinate_boundaries(client):
    for longitude, latitude in [(-180, -90), (180, 90), (0, 0)]:
        response = client.post("/api/bookmarks", json={"name": "边界", "kind": "point", "longitude": longitude, "latitude": latitude})
        assert response.status_code == 201, response.text
    identity = response.json()["id"]
    for body in ({"name": " "}, {"name": "x" * 121}, {"name": "新名", "longitude": 20}, {}):
        assert client.patch(f"/api/bookmarks/{identity}", json=body).status_code == 422


def test_map_state_defaults_partial_updates_and_metadata_reset(client):
    record = register(client)
    identity = record["id"]
    assert (record["map_attached"], record["map_visible"], record["map_opacity"]) == (False, True, 1)
    endpoint = f"/api/layers/{identity}/map-state"
    state = {"map_attached": True, "map_visible": False, "map_opacity": 0.25}
    response = client.patch(endpoint, json=state)
    assert response.status_code == 200, response.text
    assert all(response.json()[key] == value for key, value in state.items())
    response = client.patch(endpoint, json={"map_opacity": 0})
    assert response.json()["map_attached"] is True and response.json()["map_visible"] is False
    assert response.json()["map_opacity"] == 0
    assert client.patch(endpoint, json={"map_opacity": 1}).json()["map_opacity"] == 1
    metadata = {key: record[key] for key in ("name", "category", "type", "url", "source")}
    unchanged = client.patch(f"/api/layers/{identity}", json={**metadata, "name": "重命名"}).json()
    assert unchanged["map_attached"] is True
    changed = client.patch(f"/api/layers/{identity}", json={**metadata, "url": "https://example.invalid/b.geojson"}).json()
    assert changed["map_attached"] is False and changed["map_visible"] is False
    client.patch(endpoint, json={"map_attached": True})
    changed = client.patch(f"/api/layers/{identity}", json={**metadata, "type": "3dtiles"}).json()
    assert changed["map_attached"] is False
    assert client.delete(f"/api/layers/{identity}").status_code == 204
    assert client.patch(endpoint, json={"map_attached": True}).status_code == 404


@pytest.mark.parametrize("body", [
    {"map_opacity": -0.01}, {"map_opacity": 1.01}, {"map_opacity": "NaN"},
    {"map_opacity": "Infinity"}, {"map_opacity": None}, {"map_attached": None},
    {"map_visible": None}, {"map_attached": "invalid"}, {"name": "不能改名"},
])
def test_map_state_validation(client, body):
    record = register(client)
    assert client.patch(f"/api/layers/{record['id']}/map-state", json=body).status_code == 422
    saved = client.get("/api/layers").json()[0]
    assert saved["map_attached"] is False and saved["map_opacity"] == 1


def test_bookmarks_and_layer_state_survive_new_application_process(client):
    layer = register(client)
    state = {"map_attached": True, "map_visible": False, "map_opacity": 0.37}
    assert client.patch(f"/api/layers/{layer['id']}/map-state", json=state).status_code == 200
    bookmark = client.post("/api/bookmarks", json={"name": "持久化点位", "kind": "point", "longitude": 113, "latitude": 23}).json()
    script = """
import json
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    print(json.dumps({'layers': client.get('/api/layers').json(), 'bookmarks': client.get('/api/bookmarks').json()}))
"""
    result = subprocess.run([sys.executable, "-c", script], env={**os.environ, "MAP_STORAGE_DIR": str(STORAGE_DIR)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    restored = json.loads(result.stdout)
    assert restored["bookmarks"] == [bookmark]
    assert restored["layers"][0]["id"] == layer["id"]
    assert all(restored["layers"][0][key] == value for key, value in state.items())


def test_migration_preserves_layer_assets_and_files(tmp_path):
    environment = {**os.environ, "MAP_STORAGE_DIR": str(tmp_path)}
    def migrate(action, revision):
        result = subprocess.run([sys.executable, "-m", "alembic", action, revision], env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    migrate("upgrade", "0002_assets")
    retained_file = tmp_path / "files" / "asset" / "data.geojson"
    retained_file.parent.mkdir()
    retained_file.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    with closing(sqlite3.connect(tmp_path / "catalog.db")) as connection:
        connection.execute("INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("asset", "old.geojson", "geojson", "/data-files/asset/data.geojson", 42, 1, None, "2026-10-22", "active", ""))
        connection.execute("INSERT INTO layers (id, name, category, type, url, source, created_at, asset_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("old", "旧登记", "历史", "geojson", "/data-files/asset/data.geojson", "", "2026-10-22", "asset"))
        connection.commit()
    migrate("upgrade", "head")
    with closing(sqlite3.connect(tmp_path / "catalog.db")) as connection:
        assert connection.execute("SELECT name, asset_id, map_attached, map_visible, map_opacity FROM layers").fetchone() == ("旧登记", "asset", 0, 1, 1)
        assert connection.execute("SELECT original_name FROM assets").fetchone() == ("old.geojson",)
        assert connection.execute("SELECT COUNT(*) FROM bookmarks").fetchone() == (0,)
    assert retained_file.exists()
    migrate("downgrade", "0002_assets")
    with closing(sqlite3.connect(tmp_path / "catalog.db")) as connection:
        assert connection.execute("SELECT name, asset_id FROM layers").fetchone() == ("旧登记", "asset")
        assert "bookmarks" not in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert retained_file.exists()

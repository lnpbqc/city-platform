import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app import main, uploads
from app.database import FILES_DIR, STORAGE_DIR

GEO = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"名称": "小样"}, "geometry": {"type": "Point", "coordinates": [114.16, 22.29]}}]}
TILESET = {"asset": {"version": "1.1"}, "geometricError": 0, "root": {"boundingVolume": {"sphere": [0, 0, 0, 1]}, "geometricError": 0}}


def zip_data(files):
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def upload(client, content, kind="geojson", name="sample.geojson"):
    return client.post("/api/layers/upload", data={"name": "测试图层", "type": kind, "source": "合成演示"}, files={"file": (name, content)})


def test_catalog_persists_and_delete_keeps_file(client):
    response = upload(client, json.dumps(GEO).encode())
    assert response.status_code == 201, response.text
    record = response.json()
    assert client.get(record["url"]).json() == GEO
    assert client.get("/api/layers").json()[0]["id"] == record["id"]
    # A fresh database connection sees the committed record, independently of ORM state.
    with closing(sqlite3.connect(STORAGE_DIR / "catalog.db")) as connection:
        assert connection.execute("SELECT name FROM layers WHERE id = ?", (record["id"],)).fetchone() == ("测试图层",)
    updated = {k: record[k] for k in ("name", "category", "type", "url", "source")}
    updated["name"] = "已更新"
    assert client.patch(f"/api/layers/{record['id']}", json=updated).json()["name"] == "已更新"
    assert client.delete(f"/api/layers/{record['id']}").status_code == 204
    assert client.get("/api/layers").json() == []
    assert client.get(record["url"]).status_code == 200
    assert client.delete(f"/api/layers/{record['id']}").status_code == 404


def test_external_url_registration_without_fetch(client):
    body = {"name": "远程图层", "type": "3dtiles", "url": "https://example.invalid/tileset.json"}
    assert client.post("/api/layers", json=body).status_code == 201
    for url in ("D:/data/tileset.json", "javascript:alert(1)", "file:///test", "https://user:password@example.com/test"):
        assert client.post("/api/layers", json={**body, "url": url}).status_code == 422


@pytest.mark.parametrize("prefix", ["", "city/"])
def test_tiles_zip_preserves_relative_paths(client, prefix):
    files = {f"{prefix}tileset.json": json.dumps(TILESET), f"{prefix}nested/content.glb": b"sample"}
    response = upload(client, zip_data(files), "3dtiles", "city.zip")
    assert response.status_code == 201, response.text
    url = response.json()["url"]
    assert client.get(url).json() == TILESET
    assert client.get(url.removesuffix("tileset.json") + "nested/content.glb").content == b"sample"


@pytest.mark.parametrize("value", [b"broken", b"[]", b"{}", json.dumps({**GEO, "crs": {}}).encode(), json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [999, 99]}}]}).encode()])
def test_invalid_geojson_cleans_temporary_files(client, value):
    before = set(main.FILES_DIR.iterdir())
    assert upload(client, value).status_code == 422
    assert client.get("/api/layers").json() == []
    assert set(main.FILES_DIR.iterdir()) == before
    assert not list((STORAGE_DIR / "tmp").iterdir())


@pytest.mark.parametrize("bad_path", ["../escape.txt", "/absolute.txt", "D:/escape.txt", "..\\escape.txt"])
def test_zip_path_traversal(client, bad_path):
    payload = zip_data({"tileset.json": json.dumps(TILESET), bad_path: "bad"})
    assert upload(client, payload, "3dtiles", "city.zip").status_code == 422
    assert not list((STORAGE_DIR / "tmp").iterdir())


@pytest.mark.parametrize("path,message", [("nested\\model.glb", "反斜杠"), ("/model.glb", "绝对路径"), ("../model.glb", "上级目录")])
def test_zip_path_errors_explain_the_exact_reason(client, path, message):
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("tileset.json", json.dumps(TILESET))
        item = ZipInfo("placeholder")
        item.filename = path
        archive.writestr(item, "bad")
    response = upload(client, output.getvalue(), "3dtiles", "city.zip")
    assert response.status_code == 422
    assert message in response.json()["message"]
    assert response.json()["trace_id"]


@pytest.mark.parametrize("after_publish", [False, True])
def test_disconnected_upload_cleans_files_and_does_not_commit(client, monkeypatch, after_publish):
    from starlette.requests import Request
    checks = iter([False, True] if after_publish else [True])
    async def disconnected(self):
        return next(checks)
    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    response = upload(client, json.dumps(GEO).encode())
    assert response.status_code == 400
    assert client.get("/api/assets").json() == []
    assert client.get("/api/layers").json() == []
    assert not list(FILES_DIR.iterdir())
    assert not list((STORAGE_DIR / "tmp").iterdir())


def test_zip_symlink(client):
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        item = ZipInfo("link")
        item.create_system = 3
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(item, "../../outside")
    assert upload(client, output.getvalue(), "3dtiles", "city.zip").status_code == 422


def test_encrypted_zip_and_file_count(client, monkeypatch):
    content = bytearray(zip_data({"tileset.json": json.dumps(TILESET)}))
    # Mark the local and central directory entries as encrypted, without a password.
    content[6] |= 1
    central = content.index(b"PK\x01\x02")
    content[central + 8] |= 1
    assert upload(client, bytes(content), "3dtiles", "city.zip").status_code == 422
    monkeypatch.setattr(uploads, "FILE_LIMIT", 1)
    assert upload(client, zip_data({"tileset.json": json.dumps(TILESET), "extra.txt": "x"}), "3dtiles", "city.zip").status_code == 422


def test_database_failure_removes_published_upload(client, monkeypatch):
    before = set(main.FILES_DIR.iterdir())
    def fail(*args):
        raise RuntimeError("simulated database failure")
    monkeypatch.setattr(main, "create_layer", fail)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        upload(client, json.dumps(GEO).encode())
    assert set(main.FILES_DIR.iterdir()) == before
    assert not list((STORAGE_DIR / "tmp").iterdir())


@pytest.mark.parametrize("content", [b"broken", zip_data({"nested/no-entry.json": "{}"}), zip_data({"tileset.json": "{}"})])
def test_bad_tileset(client, content):
    assert upload(client, content, "3dtiles", "city.zip").status_code == 422


def test_size_and_expansion_limits(client, monkeypatch):
    monkeypatch.setattr(main, "GEOJSON_LIMIT", 16)
    assert upload(client, b" " * 17).status_code == 413
    monkeypatch.setattr(main, "ZIP_LIMIT", 16)
    assert upload(client, b" " * 17, "3dtiles", "city.zip").status_code == 413
    monkeypatch.setattr(main, "ZIP_LIMIT", 1024 * 1024)
    monkeypatch.setattr(uploads, "EXPANDED_LIMIT", 16)
    assert upload(client, zip_data({"tileset.json": " " * 100}), "3dtiles", "city.zip").status_code == 413
    assert client.get("/api/layers").json() == []


def test_multigeometry_and_polygon_validation(client):
    multi = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "MultiPolygon", "coordinates": [[[[114, 22], [115, 22], [115, 23], [114, 22]]]]}}]}
    assert upload(client, json.dumps(multi).encode()).status_code == 201
    multi["features"][0]["geometry"]["coordinates"][0][0][-1] = [114, 23]
    assert upload(client, json.dumps(multi).encode()).status_code == 422


def test_migration_round_trip(tmp_path):
    environment = {**os.environ, "MAP_STORAGE_DIR": str(tmp_path)}
    for revision in ("head", "base", "head"):
        action = "downgrade" if revision == "base" else "upgrade"
        result = subprocess.run([sys.executable, "-m", "alembic", action, revision], env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    with closing(sqlite3.connect(tmp_path / "catalog.db")) as connection:
        head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (head,)

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from app import assets
from app.database import FILES_DIR, STORAGE_DIR, SessionLocal
from app.models import Asset, Layer
from test_layers import GEO, TILESET, upload, zip_data


def body(record, **changes):
    return {**{key: record[key] for key in ("name", "category", "type", "url", "source")}, **changes}


def test_upload_records_asset_and_references(client):
    layer = upload(client, json.dumps(GEO).encode()).json()
    record = client.get(f"/api/assets/{layer['asset_id']}").json()
    assert record["original_name"] == "sample.geojson"
    assert record["entry_url"] == layer["url"]
    assert record["type"] == "geojson" and record["status"] == "active"
    assert record["uploaded_at"] and record["discovered_at"]
    for value in (layer["created_at"], record["uploaded_at"], record["discovered_at"]):
        assert datetime.fromisoformat(value).utcoffset() == timedelta(0)
    assert record["files"] == [{"path": "data.geojson", "size": len(json.dumps(GEO).encode())}]
    assert record["byte_size"] == record["files"][0]["size"]
    assert record["reference_count"] == 1
    assert record["references"] == [{"id": layer["id"], "name": layer["name"]}]


def test_tiles_asset_manages_whole_directory(client):
    layer = upload(client, zip_data({"city/tileset.json": json.dumps(TILESET), "city/nested/model.glb": b"asset"}), "3dtiles", "source.zip").json()
    record = client.get(f"/api/assets/{layer['asset_id']}").json()
    assert record["original_name"] == "source.zip"
    assert record["file_count"] == 2
    assert [item["path"] for item in record["files"]] == ["city/nested/model.glb", "city/tileset.json"]
    client.delete(f"/api/layers/{layer['id']}")
    assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 204
    assert client.get(layer["url"]).status_code == 404
    assert not (FILES_DIR / layer["asset_id"]).exists()


@pytest.mark.parametrize("prefix", ["", "http://localhost:8000", "http://127.0.0.1:5173", "http://localhost:4173"])
def test_local_absolute_addresses_share_asset_and_protect_delete(client, prefix):
    layer = upload(client, json.dumps(GEO).encode()).json()
    second = client.post("/api/layers", json=body(layer, name="第二个登记", url=prefix + layer["url"])).json()
    assert second["asset_id"] == layer["asset_id"]
    response = client.delete(f"/api/assets/{layer['asset_id']}")
    assert response.status_code == 409
    assert {item["id"] for item in response.json()["detail"]["references"]} == {layer["id"], second["id"]}
    assert client.get(layer["url"]).status_code == 200
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 409
    updated = client.patch(f"/api/layers/{second['id']}", json=body(second, url="https://example.invalid/points.geojson"))
    assert updated.status_code == 200 and updated.json()["asset_id"] is None
    assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 204


def test_scan_existing_files_is_idempotent_and_keeps_unknown_history(client):
    identity = str(uuid4())
    folder = FILES_DIR / identity
    folder.mkdir()
    (folder / "data.geojson").write_text(json.dumps(GEO), encoding="utf-8")
    with SessionLocal() as session:
        session.add(Layer(id=str(uuid4()), name="旧登记", category="历史", type="geojson", url=f"http://localhost:8000/data-files/{identity}/data.geojson", source=""))
        session.commit()
    response = client.post("/api/assets/reconcile")
    assert response.status_code == 200, response.text
    record = next(item for item in response.json()["assets"] if item["id"] == identity)
    assert record["original_name"] is None and record["uploaded_at"] is None
    assert record["reference_count"] == 1 and record["type"] == "geojson"
    assert datetime.fromisoformat(record["discovered_at"]).utcoffset() == timedelta(0)
    assert client.get("/api/layers").json()[0]["asset_id"] == identity
    assert client.post("/api/assets/reconcile").json()["discovered"] == 0
    assert folder.exists()


def test_scan_unrecognized_files_retains_asset(client):
    identity = str(uuid4())
    folder = FILES_DIR / identity
    folder.mkdir()
    (folder / "other.bin").write_bytes(b"unknown")
    response = client.post("/api/assets/reconcile")
    record = next(item for item in response.json()["assets"] if item["id"] == identity)
    assert record["type"] == "unknown" and record["entry_url"] is None
    assert record["file_count"] == 1


def test_retained_file_can_be_registered_again(client):
    layer = upload(client, json.dumps(GEO).encode()).json()
    client.delete(f"/api/layers/{layer['id']}")
    assert client.get(f"/api/assets/{layer['asset_id']}").json()["reference_count"] == 0
    response = client.post("/api/layers", json=body(layer))
    assert response.status_code == 201 and response.json()["asset_id"] == layer["asset_id"]


def test_asset_deletion_failure_blocks_references_and_retries(client, monkeypatch):
    layer = upload(client, json.dumps(GEO).encode()).json()
    client.delete(f"/api/layers/{layer['id']}")
    original_remove = assets.shutil.rmtree
    def fail(path):
        raise PermissionError("simulated file in use")
    monkeypatch.setattr(assets.shutil, "rmtree", fail)
    response = client.delete(f"/api/assets/{layer['asset_id']}")
    assert response.status_code == 500
    record = client.get(f"/api/assets/{layer['asset_id']}").json()
    assert record["status"] == "delete_error" and "simulated" in record["error"]
    assert (STORAGE_DIR / "deleting" / layer["asset_id"]).is_dir()
    assert client.get(layer["url"]).status_code == 404
    assert client.post("/api/layers", json=body(layer)).status_code == 409
    monkeypatch.setattr(assets.shutil, "rmtree", original_remove)
    assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 204
    assert client.get(f"/api/assets/{layer['asset_id']}").status_code == 404


@pytest.mark.parametrize("path", ["../outside.geojson", "%2e%2e/outside.geojson", "nested%5c..%5coutside.geojson", "D:/outside.geojson", "missing.geojson"])
def test_registration_rejects_unsafe_or_missing_local_paths(client, path):
    layer = upload(client, json.dumps(GEO).encode()).json()
    response = client.post("/api/layers", json=body(layer, url=f"/data-files/{layer['asset_id']}/{path}"))
    assert response.status_code == 422


def test_missing_or_deleting_asset_rejects_registration(client):
    layer = upload(client, json.dumps(GEO).encode()).json()
    assert client.post("/api/layers", json=body(layer, url=f"/data-files/{uuid4()}/data.geojson")).status_code == 422
    (FILES_DIR / layer["asset_id"] / "data.geojson").unlink()
    assert client.get(f"/api/assets/{layer['asset_id']}").json()["status"] == "missing"
    assert client.post("/api/layers", json=body(layer)).status_code == 422
    with SessionLocal() as session:
        session.get(Asset, layer["asset_id"]).status = "deleting"
        session.commit()
    assert client.post("/api/layers", json=body(layer)).status_code == 409


def test_external_same_path_is_not_a_local_asset(client):
    layer = upload(client, json.dumps(GEO).encode()).json()
    for prefix in ("https://example.invalid", "http://localhost:9999", "http://127.0.0.1:80"):
        response = client.post("/api/layers", json=body(layer, url=prefix + layer["url"]))
        assert response.status_code == 201 and response.json()["asset_id"] is None
    assert client.post("/api/layers", json=body(layer, url="http://localhost:broken" + layer["url"])).status_code == 422


def test_duplicate_delete_and_new_reference_during_cleanup(client, monkeypatch):
    layer = upload(client, json.dumps(GEO).encode()).json()
    client.delete(f"/api/layers/{layer['id']}")
    entered, release = Event(), Event()
    original_remove = assets.shutil.rmtree
    def slow_remove(path):
        entered.set()
        assert release.wait(5)
        original_remove(path)
    monkeypatch.setattr(assets.shutil, "rmtree", slow_remove)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.delete, f"/api/assets/{layer['asset_id']}")
        assert entered.wait(5)
        assert client.post("/api/layers", json=body(layer)).status_code == 409
        second = executor.submit(client.delete, f"/api/assets/{layer['asset_id']}")
        release.set()
        assert first.result().status_code == 204
        assert second.result().status_code == 404
    assert client.get(f"/api/assets/{layer['asset_id']}").status_code == 404


@pytest.mark.parametrize("nested", [False, True])
def test_delete_and_scan_reject_directory_links(client, nested):
    identity = str(uuid4())
    outside = STORAGE_DIR / f"protected-{uuid4()}"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("protected", encoding="utf-8")
    folder = FILES_DIR / identity
    if nested:
        folder.mkdir()
    link = folder / "linked" if nested else folder
    try:
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
        else:
            link.symlink_to(outside, target_is_directory=True)
        response = client.post("/api/assets/reconcile")
        record = next(item for item in response.json()["assets"] if item["id"] == identity)
        assert record["status"] == "unsafe"
        assert client.get(f"/api/assets/{identity}/download").status_code == 409
        assert client.delete(f"/api/assets/{identity}").status_code == 500
        assert marker.read_text(encoding="utf-8") == "protected"
    finally:
        if link.is_junction():
            os.rmdir(link)
        elif link.is_symlink():
            link.unlink()


def test_invalid_asset_identity_cannot_escape_storage(client):
    outside = STORAGE_DIR / "keep.txt"
    outside.write_text("keep", encoding="utf-8")
    with SessionLocal() as session:
        session.add(Asset(id="..", original_name=None, type="unknown", entry_url=None, byte_size=0, file_count=0, uploaded_at=None, status="active", error=""))
        session.commit()
    assert client.delete("/api/assets/%2E%2E").status_code == 500
    assert outside.read_text(encoding="utf-8") == "keep"


def test_asset_migration_preserves_old_layer_rows(tmp_path):
    environment = {**os.environ, "MAP_STORAGE_DIR": str(tmp_path)}
    def migrate(action, revision):
        result = subprocess.run([sys.executable, "-m", "alembic", action, revision], env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    migrate("upgrade", "0001_layers")
    with closing(sqlite3.connect(tmp_path / "catalog.db")) as connection:
        connection.execute("INSERT INTO layers VALUES (?, ?, ?, ?, ?, ?, ?)", ("old", "旧记录", "历史", "geojson", "https://example.invalid/test.geojson", "来源", "2026-10-22"))
        connection.commit()
    migrate("upgrade", "head")
    with closing(sqlite3.connect(tmp_path / "catalog.db")) as connection:
        assert connection.execute("SELECT name, asset_id FROM layers").fetchone() == ("旧记录", None)
    migrate("downgrade", "0001_layers")
    with closing(sqlite3.connect(tmp_path / "catalog.db")) as connection:
        assert connection.execute("SELECT name FROM layers").fetchone() == ("旧记录",)

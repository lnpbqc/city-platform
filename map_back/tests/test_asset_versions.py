import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import FILES_DIR, SessionLocal
from app.models import Asset, AssetVersion, Layer


def upload(client):
    return client.post("/api/layers/upload", data={"name": "版本测试", "type": "geojson"},
                       files={"file": ("sample.geojson", b'{"type":"FeatureCollection","features":[]}', "application/json")}).json()


def test_upload_creates_initial_version_and_binds_layer(client):
    layer = upload(client)
    assert layer["asset_version"] == "1.0.0"
    asset = client.get(f"/api/assets/{layer['asset_id']}").json()
    assert asset["current_version"] == "1.0.0"
    assert asset["source_kind"] == "upload"
    assert asset["protected"] is False
    with SessionLocal() as session:
        row = session.execute(text("SELECT version, entry_url, file_count FROM asset_versions WHERE asset_id=:id"), {"id": layer["asset_id"]}).one()
        assert tuple(row) == ("1.0.0", layer["url"], 1)


def test_protected_asset_keeps_files_but_layer_registration_can_be_removed(client):
    layer = upload(client)
    path = FILES_DIR / layer["asset_id"] / "data.geojson"
    before = path.read_bytes()
    with SessionLocal() as session:
        asset = session.get(Asset, layer["asset_id"])
        asset.source_kind = "default"
        asset.protected = True
        session.commit()
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    response = client.delete(f"/api/assets/{layer['asset_id']}")
    assert response.status_code == 403
    assert response.json()["code"] == "ASSET_PROTECTED"
    assert path.read_bytes() == before
    assert client.get(f"/api/assets/{layer['asset_id']}").json()["protected"] is True


def test_changing_layer_to_external_url_clears_asset_version(client):
    layer = upload(client)
    response = client.patch(f"/api/layers/{layer['id']}", json={
        "name": "外部图层", "type": "geojson", "url": "https://example.invalid/model.geojson",
    })
    assert response.status_code == 200
    assert response.json()["asset_id"] is None
    assert response.json()["asset_version"] is None


def test_reconcile_creates_one_initial_version_without_moving_files(client):
    identity = str(uuid4())
    folder = FILES_DIR / identity
    folder.mkdir()
    data = b'{"type":"FeatureCollection","features":[]}'
    path = folder / "data.geojson"
    path.write_bytes(data)
    for _ in range(2):
        assert client.post("/api/assets/reconcile").status_code == 200
    with SessionLocal() as session:
        assert session.execute(text("SELECT COUNT(*) FROM asset_versions WHERE asset_id=:id"), {"id": identity}).scalar_one() == 1
    assert path.read_bytes() == data


def test_published_version_core_fields_are_immutable(client):
    layer = upload(client)
    with SessionLocal() as session:
        with pytest.raises(IntegrityError, match="资产版本不可修改"):
            session.execute(text("UPDATE asset_versions SET entry_url='changed' WHERE asset_id=:id"), {"id": layer["asset_id"]})
        session.rollback()
        assert session.execute(text("SELECT entry_url FROM asset_versions WHERE asset_id=:id"), {"id": layer["asset_id"]}).scalar_one() == layer["url"]


def test_unreferenced_upload_deletion_also_removes_version_records(client):
    layer = upload(client)
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 204
    with SessionLocal() as session:
        assert session.execute(text("SELECT COUNT(*) FROM asset_versions WHERE asset_id=:id"), {"id": layer["asset_id"]}).scalar_one() == 0


def test_scan_keeps_version_reference_when_old_entry_is_missing(client):
    layer = upload(client)
    folder = FILES_DIR / layer["asset_id"]
    (folder / "data.geojson").rename(folder / "replacement.geojson")
    with SessionLocal() as session:
        record = session.get(Layer, layer["id"])
        record.asset_id = None
        record.asset_version = None
        session.commit()
    assert client.post("/api/assets/reconcile").status_code == 200
    record = client.get("/api/layers").json()[0]
    assert record["asset_id"] == layer["asset_id"]
    assert record["asset_version"] == "1.0.0"
    assert record["url"] == layer["url"]


@pytest.mark.parametrize("operation", ["scan", "rename"])
def test_existing_layer_stays_pinned_when_current_asset_version_advances(client, operation):
    layer = upload(client)
    with SessionLocal() as session:
        asset = session.get(Asset, layer["asset_id"])
        session.add(AssetVersion(asset_id=asset.id, version="2.0.0", entry_url=asset.entry_url,
                                 byte_size=asset.byte_size, file_count=asset.file_count))
        asset.current_version = "2.0.0"
        session.commit()
    if operation == "scan":
        assert client.post("/api/assets/reconcile").status_code == 200
        record = client.get("/api/layers").json()[0]
    else:
        response = client.patch(f"/api/layers/{layer['id']}", json={"name": "仅改名称", "type": "geojson", "url": layer["url"]})
        assert response.status_code == 200
        record = response.json()
    assert record["asset_version"] == "1.0.0"
    new_record = client.post("/api/layers", json={"name": "新增登记", "type": "geojson", "url": layer["url"]})
    assert new_record.status_code == 201
    assert new_record.json()["asset_version"] == "2.0.0"


def test_version_migration_preserves_existing_ids_urls_and_file_bytes(tmp_path):
    environment = {**os.environ, "MAP_STORAGE_DIR": str(tmp_path)}

    def migrate(action, revision):
        result = subprocess.run([sys.executable, "-m", "alembic", action, revision], env=environment, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    migrate("upgrade", "0003_bookmarks_map_state")
    identity = str(uuid4())
    entry = f"/data-files/{identity}/data.geojson"
    path = tmp_path / "files" / identity / "data.geojson"
    path.parent.mkdir()
    path.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(tmp_path / "catalog.db")) as connection:
        connection.execute("INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (identity, "old.geojson", "geojson", entry, path.stat().st_size, 1, None, "2026-10-25", "active", ""))
        connection.execute("INSERT INTO layers (id,name,category,type,url,source,created_at,asset_id) VALUES (?,?,?,?,?,?,?,?)",
                           ("old-layer", "旧登记", "历史", "geojson", entry, "来源", "2026-10-25", identity))
        connection.commit()
    migrate("upgrade", "head")
    with closing(sqlite3.connect(tmp_path / "catalog.db")) as connection:
        assert connection.execute("SELECT id,entry_url,current_version,source_kind,protected FROM assets").fetchone() == (identity, entry, "1.0.0", "upload", 0)
        assert connection.execute("SELECT asset_id,asset_version,url FROM layers").fetchone() == (identity, "1.0.0", entry)
        assert connection.execute("SELECT asset_id,version,entry_url FROM asset_versions").fetchone() == (identity, "1.0.0", entry)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    migrate("downgrade", "0003_bookmarks_map_state")
    with closing(sqlite3.connect(tmp_path / "catalog.db")) as connection:
        assert connection.execute("SELECT id,entry_url FROM assets").fetchone() == (identity, entry)
        assert "asset_versions" not in {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest

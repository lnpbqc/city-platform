import hashlib
import io
import json
from uuid import uuid4
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import FILES_DIR, SessionLocal
from app.main import app
from app.models import Asset, AssetVersion
from test_layers import GEO, TILESET, upload, zip_data


def register(client, location="https://example.invalid/city/tileset.json"):
    return client.post("/api/assets/register", json={
        "name": "外部场景", "type": "3dtiles", "location": location,
        "source": "提供方", "coordinate_description": "WGS84，已配准",
    })


def test_external_asset_registers_without_moving_or_fetching_files(client):
    before = set(FILES_DIR.iterdir())
    response = register(client)
    assert response.status_code == 201, response.text
    asset = response.json()
    assert asset["version"] == "1.0.0" and asset["source_kind"] == "external"
    assert asset["name"] == "外部场景" and asset["source"] == "提供方"
    assert asset["byte_size"] is None and asset["file_count"] is None
    assert asset["sha256"] is None and asset["bounds"] is None
    assert set(FILES_DIR.iterdir()) == before
    detail = client.get(f"/api/assets/{asset['asset_id']}").json()
    assert detail["status"] == "active" and detail["files"] == []
    assert detail["byte_size"] is None


def test_duplicate_external_registration_uses_canonical_host_and_default_port(client):
    assert register(client, "https://EXAMPLE.invalid:443/city/tileset.json").status_code == 201
    response = register(client)
    assert response.status_code == 409
    assert response.json()["code"] == "ASSET_ALREADY_REGISTERED"


@pytest.mark.parametrize("location", [r"D:\private\model.fbx", "/private/model.json", "file:///D:/private/model.json", "https://user:password@example.invalid/a.json"])
def test_asset_registration_rejects_disk_paths_and_embedded_credentials(client, location):
    assert register(client, location).status_code == 422


def test_existing_managed_asset_registration_returns_conflict_without_copying(client):
    layer = upload(client, json.dumps(GEO).encode()).json()
    response = client.post("/api/assets/register", json={"name": "重复", "type": "geojson", "location": layer["url"]})
    assert response.status_code == 409
    assert len(client.get("/api/assets").json()) == 1


def test_external_asset_layer_reference_and_deletion_only_remove_records(client):
    asset = register(client).json()
    identity = asset["asset_id"]
    response = client.post("/api/layers", json={"name": "外部图层", "type": "3dtiles", "url": asset["entry_url"]})
    assert response.status_code == 201, response.text
    layer = response.json()
    assert layer["asset_id"] == identity and layer["asset_version"] == "1.0.0"
    assert layer["asset_source_kind"] == "external"
    assert client.delete(f"/api/assets/{identity}").status_code == 409
    assert client.get(f"/api/assets/{identity}/download").status_code == 409
    client.delete(f"/api/layers/{layer['id']}")
    sentinel = FILES_DIR / identity
    sentinel.mkdir()
    (sentinel / "keep.txt").write_text("原文件", encoding="utf-8")
    assert client.delete(f"/api/assets/{identity}").status_code == 204
    assert (sentinel / "keep.txt").read_text(encoding="utf-8") == "原文件"


def test_upload_exposes_stable_hashes_and_real_geojson_bounds(client):
    payload = json.dumps(GEO).encode()
    layer = upload(client, payload).json()
    detail = client.get(f"/api/assets/{layer['asset_id']}").json()
    files = [{"path": "data.geojson", "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}]
    expected = hashlib.sha256(json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert detail["sha256"] == expected
    assert detail["file_checksums"] == files
    assert detail["bounds"] == {"west": 114.16, "south": 22.29, "east": 114.16, "north": 22.29, "min_height": None, "max_height": None}
    assert detail["source"] == "合成演示"
    versions = client.get(f"/api/assets/{layer['asset_id']}/versions").json()
    assert len(versions) == 1 and versions[0]["version"] == "1.0.0"
    version = client.get(f"/api/assets/{layer['asset_id']}/versions/1.0.0").json()
    assert version["sha256"] == expected
    assert version["file_checksums"] == files
    assert client.get(f"/api/assets/{layer['asset_id']}/versions/absent").status_code == 404


def test_tiles_download_preserves_every_file_checksum(client):
    files = {"tileset.json": json.dumps(TILESET).encode(), "nested/model.glb": b"model", "textures/wall.png": b"texture"}
    layer = upload(client, zip_data(files), "3dtiles", "model.zip").json()
    detail = client.get(f"/api/assets/{layer['asset_id']}").json()
    response = client.get(f"/api/assets/{layer['asset_id']}/download")
    assert response.status_code == 200
    with ZipFile(io.BytesIO(response.content)) as archive:
        for item in detail["file_checksums"]:
            assert hashlib.sha256(archive.read(item["path"])).hexdigest() == item["sha256"]


def test_changed_published_content_does_not_replace_version_fingerprint(client):
    layer = upload(client, json.dumps(GEO).encode()).json()
    path = f"/api/assets/{layer['asset_id']}"
    original = client.get(path).json()["sha256"]
    (FILES_DIR / layer["asset_id"] / "data.geojson").write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    response = client.get(path + "/download")
    assert response.status_code == 409
    assert response.json()["code"] == "ASSET_CONTENT_CHANGED"
    client.post("/api/assets/reconcile")
    detail = client.get(path).json()
    assert detail["status"] == "unsafe" and detail["sha256"] == original


def test_captured_fingerprint_cannot_be_overwritten_in_database(client):
    layer = upload(client, json.dumps(GEO).encode()).json()
    with SessionLocal() as session:
        with pytest.raises(IntegrityError, match="资产校验和不可修改"):
            session.execute(text("UPDATE asset_versions SET sha256='changed' WHERE asset_id=:id"), {"id": layer["asset_id"]})
        session.rollback()


def test_backfilled_version_reports_measured_file_count(client):
    identity = str(uuid4())
    folder = FILES_DIR / identity
    folder.mkdir()
    (folder / "data.geojson").write_text(json.dumps(GEO), encoding="utf-8")
    (folder / "source.txt").write_text("来源", encoding="utf-8")
    entry = f"/data-files/{identity}/data.geojson"
    with SessionLocal() as session:
        session.add(Asset(id=identity, original_name=None, type="geojson", entry_url=entry, byte_size=0, file_count=0, status="active", error=""))
        session.flush()
        session.add(AssetVersion(asset_id=identity, version="1.0.0", entry_url=entry, byte_size=0, file_count=0))
        session.commit()
    assert client.post("/api/assets/reconcile").status_code == 200
    response = client.get(f"/api/assets/{identity}/versions/1.0.0")
    assert response.json()["file_count"] == len(response.json()["file_checksums"]) == 2


def test_startup_reconciles_historical_files_and_metadata(client):
    identity = str(uuid4())
    folder = FILES_DIR / identity
    folder.mkdir()
    (folder / "data.geojson").write_text(json.dumps(GEO), encoding="utf-8")
    with TestClient(app) as restarted:
        response = restarted.get(f"/api/assets/{identity}")
    assert response.status_code == 200
    assert response.json()["sha256"]
    assert response.json()["current_version"] == "1.0.0"

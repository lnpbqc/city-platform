import io
import json
from uuid import uuid4
from zipfile import ZipFile

import pytest

from app import assets
from app.database import FILES_DIR, STORAGE_DIR, SessionLocal
from app.models import Asset
from test_layers import GEO, TILESET, upload, zip_data


def temporary_downloads():
    return set((STORAGE_DIR / "tmp").glob("download-*"))


def test_geojson_download_is_exact_and_retains_asset_and_registration(client):
    payload = json.dumps(GEO).encode()
    layer = upload(client, payload).json()
    before = temporary_downloads()
    response = client.get(f"/api/assets/{layer['asset_id']}/download")
    assert response.status_code == 200
    assert response.content == payload
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["content-type"].startswith("application/geo+json")
    assert client.get(layer["url"]).content == payload
    assert client.get("/api/layers").json()[0]["id"] == layer["id"]
    assert temporary_downloads() == before


def test_tiles_download_preserves_entire_published_directory(client):
    files = {"campus/tileset.json": json.dumps(TILESET).encode(),
             "campus/nested/model.glb": b"model", "campus/textures/wall.png": b"texture"}
    layer = upload(client, zip_data(files), "3dtiles", "campus.zip").json()
    before = temporary_downloads()
    response = client.get(f"/api/assets/{layer['asset_id']}/download")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == set(files)
        for path, payload in files.items():
            assert archive.read(path) == payload
            assert (FILES_DIR / layer["asset_id"] / path).read_bytes() == payload
    assert temporary_downloads() == before


@pytest.mark.parametrize("status", ["deleting", "delete_error", "unsafe"])
def test_download_rejects_unavailable_assets(client, status):
    layer = upload(client, json.dumps(GEO).encode()).json()
    with SessionLocal() as session:
        session.get(Asset, layer["asset_id"]).status = status
        session.commit()
    assert client.get(f"/api/assets/{layer['asset_id']}/download").status_code == 409


def test_download_rejects_missing_files_and_unrecognized_identity(client):
    assert client.get(f"/api/assets/{uuid4()}/download").status_code == 404
    layer = upload(client, json.dumps(GEO).encode()).json()
    (FILES_DIR / layer["asset_id"] / "data.geojson").unlink()
    assert client.get(f"/api/assets/{layer['asset_id']}/download").status_code == 409
    with SessionLocal() as session:
        session.add(Asset(id="..", original_name=None, type="unknown", entry_url=None, byte_size=0, file_count=0, uploaded_at=None, status="active", error=""))
        session.commit()
    assert client.get("/api/assets/%2E%2E/download").status_code == 409


def test_failed_packaging_cleans_partial_download_and_can_retry(client, monkeypatch):
    layer = upload(client, zip_data({"tileset.json": json.dumps(TILESET)}), "3dtiles", "sample.zip").json()
    original = assets.ZipFile.write
    def fail(*args, **kwargs):
        raise OSError("simulated packaging failure")
    before = temporary_downloads()
    monkeypatch.setattr(assets.ZipFile, "write", fail)
    assert client.get(f"/api/assets/{layer['asset_id']}/download").status_code == 409
    assert temporary_downloads() == before
    assert client.get(layer["url"]).status_code == 200
    monkeypatch.setattr(assets.ZipFile, "write", original)
    assert client.get(f"/api/assets/{layer['asset_id']}/download").status_code == 200

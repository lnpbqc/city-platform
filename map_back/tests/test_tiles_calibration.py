import io
import hashlib
import json
import os
import random
import shutil
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote
from zipfile import ZipFile

from app.database import FILES_DIR, SessionLocal
from app.services.tiles_download import CHUNK_SIZE, stream_zip

from test_layers import upload, zip_data
from test_scenes import draft, layer_state


TRANSFORM = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 20, 30, 1]
ROOT = {
    "asset": {"version": "1.1"},
    "geometricError": 0,
    "root": {
        "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 6378137, 0, 0, 1],
        "boundingVolume": {"box": [0, 0, 0, 10, 0, 0, 0, 10, 0, 0, 0, 10]},
        "geometricError": 0,
        "content": {"uri": "nested/model.glb"},
    },
}


def prepare(client):
    original = json.dumps(ROOT).encode()
    files = {"project/tileset.json": original, "project/nested/model.glb": b"model"}
    response = upload(client, zip_data(files), "3dtiles", "林芝.zip")
    assert response.status_code == 201, response.text
    return response.json(), original


def request_body(mode="update", revision=0, **changes):
    return {"base_version": "1.0.0", "base_revision": revision, "mode": mode, "matrix": TRANSFORM,
            "terrain_anchor": {"longitude": 0.001, "latitude": 0.002, "height": 2950}, **changes}


def test_update_replaces_original_manifests_and_both_downloads(client):
    layer, original = prepare(client)
    identity = layer["asset_id"]
    base = f"/api/assets/{identity}"
    duplicate = client.post("/api/layers", json={"name": "第二图层", "type": "3dtiles", "url": layer["url"]}).json()
    for row in (layer, duplicate):
        assert client.patch(f"/api/layers/catalog/{row['id']}/map-state", json={
            "tiles_height_offset_m": 17, "tiles_align_to_terrain": True,
        }).status_code == 200
    initial_sha = client.get(base).json()["sha256"]
    response = client.post(f"{base}/versions/calibrate", json=request_body())
    assert response.status_code == 201, response.text
    version = response.json()
    assert version["asset_id"] == identity and version["version"] == "1.0.0"
    assert version["revision"] == 1 and version["tiles_calibrated"]
    assert version["entry_url"] == layer["url"]
    assert version["sha256"] != initial_sha
    updated_json = client.get(layer["url"])
    assert updated_json.headers["Cache-Control"] == "no-store"
    assert updated_json.content != original
    assert updated_json.json()["root"]["transform"][12:15] == [6378147, 20, 30]
    assert (FILES_DIR / identity / "project/tileset.json").read_bytes() == updated_json.content
    catalog = {row["id"]: row for row in client.get("/api/layers/catalog").json()}
    for row in (layer, duplicate):
        refreshed = catalog[row["id"]]
        assert refreshed["asset"]["version"] == "1.0.0"
        assert refreshed["url"] == layer["url"] and refreshed["tiles_calibrated"]
        assert refreshed["tiles_height_offset_m"] == 0 and refreshed["tiles_align_to_terrain"] is False
        assert refreshed["tiles_revision"] == 1
        assert refreshed["tiles_terrain_anchor"] == request_body()["terrain_anchor"]
    fresh = client.post("/api/layers", json={"name": "第三图层", "type": "3dtiles", "url": layer["url"]})
    assert fresh.status_code == 201 and fresh.json()["tiles_align_to_terrain"] is False
    detail = client.get(base).json()
    assert detail["tiles_calibrated"] and detail["revision"] == 1
    for path in ("/download", "/versions/1.0.0/download?revision=1"):
        response = client.get(base + path)
        assert response.status_code == 200
        with ZipFile(io.BytesIO(response.content)) as package:
            assert package.read("project/tileset.json") == updated_json.content
            assert package.read("project/nested/model.glb") == b"model"
        assert f"{detail['name']}.zip" in unquote(response.headers["Content-Disposition"])
    assert client.head(f"{base}/versions/1.0.0/download?revision=0").status_code == 409
    assert client.post("/api/assets/reconcile").status_code == 200
    assert client.get(base).json()["status"] == "active"


def test_save_as_copies_package_with_its_own_identity_and_no_layer(client):
    layer, original = prepare(client)
    identity = layer["asset_id"]
    base = f"/api/assets/{identity}"
    response = client.post(f"{base}/versions/calibrate", json=request_body("copy", name="另一份林芝"))
    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["asset_id"] != identity and copy["name"] == "另一份林芝"
    assert copy["version"] == "1.0.0" and copy["revision"] == 1
    assert client.get(copy["entry_url"]).json()["root"]["transform"][12:15] == [6378147, 20, 30]
    assert client.get(layer["url"]).content == original
    assert not client.get(f"/api/assets/{copy['asset_id']}").json()["references"]
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    assert client.delete(base).status_code == 204
    with ZipFile(io.BytesIO(client.get(f"/api/assets/{copy['asset_id']}/download").content)) as archived:
        assert archived.read("project/nested/model.glb") == b"model"
    registered = client.post("/api/layers", json={"name": "另一份林芝", "type": "3dtiles", "url": copy["entry_url"]})
    assert registered.status_code == 201, registered.text
    assert registered.json()["asset_id"] == copy["asset_id"]
    assert client.delete(f"/api/assets/{copy['asset_id']}").status_code == 409
    assert client.delete(f"/api/layers/{registered.json()['id']}").status_code == 204
    assert client.delete(f"/api/assets/{copy['asset_id']}").status_code == 204


def test_calibration_detects_conflicts_and_rejects_nonrigid_matrix(client):
    layer, _ = prepare(client)
    base = f"/api/assets/{layer['asset_id']}/versions/calibrate"
    assert client.post(base, json=request_body(matrix=[2, *TRANSFORM[1:]])).status_code == 422
    with ThreadPoolExecutor(max_workers=2) as workers:
        statuses = list(workers.map(lambda _: client.post(base, json=request_body()).status_code, range(2)))
    assert sorted(statuses) == [201, 409]


def test_legacy_current_package_can_be_copied_and_updated(client, monkeypatch):
    from app.models import Asset, AssetVersion, Layer
    from app.services.assets import TILES_VERSIONS_DIR
    from app.services import tiles_calibration

    layer, original = prepare(client)
    identity = layer["asset_id"]
    number = "1.0.1"
    storage = TILES_VERSIONS_DIR / identity / number
    url = f"/api/assets/{identity}/versions/{number}/tiles/project/tileset.json"
    shutil.copytree(FILES_DIR / identity, storage)
    with SessionLocal() as session:
        asset = session.get(Asset, identity)
        base = session.get(AssetVersion, (identity, "1.0.0"))
        session.add(AssetVersion(asset_id=identity, version=number, entry_url=url, tiles_calibrated=True,
                                 byte_size=base.byte_size, file_count=base.file_count, sha256=base.sha256,
                                 file_manifest=base.file_manifest, bounds=base.bounds))
        session.flush()
        asset.current_version, asset.entry_url = number, url
        registered = session.get(Layer, layer["id"])
        registered.asset_version, registered.url = number, url
        session.commit()
    endpoint = f"/api/assets/{identity}/versions/calibrate"
    copied = client.post(endpoint, json=request_body("copy", base_version=number, name="旧校准包副本"))
    assert copied.status_code == 201, copied.text
    assert copied.json()["asset_id"] != identity
    assert client.get(url).content == original

    with monkeypatch.context() as patch:
        patch.setattr(tiles_calibration, "index_asset", lambda *_: None)
        failed = client.post(endpoint, json=request_body(base_version=number))
        assert failed.status_code == 409, failed.text
    assert client.get(url).content == original
    updated = client.post(endpoint, json=request_body(base_version=number))
    assert updated.status_code == 201, updated.text
    assert updated.json()["revision"] == 1 and updated.json()["entry_url"] == url
    assert (FILES_DIR / identity / "project/tileset.json").read_bytes() == original
    active_manifest = client.get(url)
    assert active_manifest.headers["Cache-Control"] == "no-store"
    assert active_manifest.json()["root"]["transform"][12:15] == [6378147, 20, 30]
    response = client.get(f"/api/assets/{identity}/versions/{number}/download?revision=1")
    assert response.status_code == 200, response.text
    with ZipFile(io.BytesIO(response.content)) as package:
        assert package.read("project/tileset.json") == active_manifest.content
        assert package.read("project/nested/model.glb") == b"model"


def test_saved_scene_reads_current_model_and_preserves_run_request(client):
    layer, _ = prepare(client)
    base = f"/api/assets/{layer['asset_id']}"
    scene = client.post("/api/scenes", json={**draft(), "layers": [layer_state(layer)]})
    assert scene.status_code == 201, scene.text
    saved = scene.json()
    run = client.post("/api/runs", json={
        "scene_id": saved["id"], "network": saved["network"], "origin": "S", "destination": "T",
    })
    assert run.status_code == 201, run.text
    input_path = f"/api/runs/{run.json()['run_id']}/input"
    original_run = client.get(input_path).json()
    first = client.post(f"{base}/versions/calibrate", json=request_body())
    assert first.status_code == 201, first.text
    second = client.post(f"{base}/versions/calibrate", json=request_body(revision=1))
    assert second.status_code == 201, second.text
    assert second.json()["version"] == "1.0.0" and second.json()["revision"] == 2
    assert client.get(f"/api/scenes/{saved['id']}").json() == saved
    assert client.get(input_path).json() == original_run
    ref = saved["layers"][0]["asset"]
    saved_asset = client.get(f"/api/assets/{ref['asset_id']}/versions/{ref['version']}").json()
    assert client.get(saved_asset["entry_url"]).json()["root"]["transform"][12:15] == [6378157, 40, 60]


def test_catches_mid_publication_failure_and_keeps_original(client, monkeypatch):
    layer, original = prepare(client)
    base = f"/api/assets/{layer['asset_id']}"
    from app.services import tiles_calibration

    def fail_index(*args):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(tiles_calibration, "index_asset", fail_index)
    response = client.post(f"{base}/versions/calibrate", json=request_body())
    assert response.status_code == 409, response.text
    assert client.get(layer["url"]).content == original
    assert client.get(base).json()["revision"] == 0


def test_download_snapshot_survives_later_update(client):
    from app.services.tiles_download import download_version
    import shutil

    layer, original = prepare(client)
    with SessionLocal() as session:
        snapshot, files, _ = download_version(session, layer["asset_id"], "1.0.0")
    try:
        response = client.post(f"/api/assets/{layer['asset_id']}/versions/calibrate", json=request_body())
        assert response.status_code == 201, response.text
        with ZipFile(io.BytesIO(b"".join(stream_zip(snapshot, files)))) as package:
            assert package.read("project/tileset.json") == original
    finally:
        shutil.rmtree(snapshot)


def test_damaged_payload_is_rejected_before_zip_response(client):
    layer, _ = prepare(client)
    identity = layer["asset_id"]
    (FILES_DIR / identity / "project/nested/model.glb").write_bytes(b"other")
    url = f"/api/assets/{identity}/versions/1.0.0/download?revision=0"
    head = client.head(url)
    assert head.status_code == 409
    assert "project/nested/model.glb" in unquote(head.headers["X-Download-Error"])
    response = client.get(url)
    assert response.status_code == 409
    assert response.json()["code"] == "ASSET_CONTENT_CHANGED"


def test_updates_nested_region_manifest_at_original_location(client):
    root = {**ROOT, "root": {**ROOT["root"], "content": {"uri": "nested/child.JSON"}}}
    nested = {**ROOT, "root": {
        "boundingVolume": {"region": [0, 0, 0.001, 0.001, 5, 15]},
        "geometricError": 0, "content": {"uri": "model.glb"},
    }}
    files = {"project/tileset.json": json.dumps(root).encode(),
             "project/nested/child.JSON": json.dumps(nested).encode(),
             "project/nested/model.glb": b"model"}
    layer = upload(client, zip_data(files), "3dtiles", "101.zip").json()
    base = f"/api/assets/{layer['asset_id']}"
    response = client.post(f"{base}/versions/calibrate", json=request_body())
    assert response.status_code == 201, response.text
    child_url = layer["url"].replace("tileset.json", "nested/child.JSON")
    child = client.get(child_url)
    assert child.headers["Cache-Control"] == "no-store"
    assert "box" in child.json()["root"]["boundingVolume"]
    with ZipFile(io.BytesIO(client.get(base + "/download").content)) as archived:
        assert archived.read("project/nested/child.JSON") == child.content


def test_recovers_interrupted_update_before_catalog_startup(client):
    from app.services.layer_catalog import initialize_catalog
    from app.services.tiles_calibration import _journal, temporary_tile_directory

    layer, original = prepare(client)
    identity = layer["asset_id"]
    relative = "project/tileset.json"
    source = FILES_DIR / identity / relative
    stage = temporary_tile_directory("tiles-publish-")
    backup = stage / "backup" / relative
    backup.parent.mkdir(parents=True)
    os.link(source, backup)
    _journal(stage, mode="update", asset_id=identity, version="1.0.0", revision=1, paths=[relative])
    replacement = stage / "replacement"
    replacement.write_bytes(b"uncommitted manifest")
    replacement.replace(source)
    with SessionLocal() as session:
        initialize_catalog(session)
    assert source.read_bytes() == original
    assert not stage.exists()


def test_zip_stream_yields_bounded_chunks_for_large_incompressible_content(tmp_path):
    filename = "nested/payload.b3dm"
    file = tmp_path / filename
    file.parent.mkdir()
    data = random.Random(4242).randbytes(8 * CHUNK_SIZE)
    file.write_bytes(data)
    files = [{"path": filename, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]
    chunks = list(stream_zip(tmp_path, files))
    assert len(chunks) >= 5
    assert max(map(len, chunks)) < 3 * CHUNK_SIZE
    with ZipFile(io.BytesIO(b"".join(chunks))) as package:
        assert package.read(filename) == data

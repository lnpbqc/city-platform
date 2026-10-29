import hashlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from threading import Event

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

from app import assets, runs, scenes
from app.builtin_assets import builtin_asset_files, builtin_asset_id, ensure_builtin_assets
from app.database import FILES_DIR, SessionLocal
from app.models import AssetVersion, NetworkVersion
from app.run_store import claim_next, finish_run
from app.run_worker import RunQueue
from test_scenes import draft, layer_state, upload


@pytest.fixture
def stopped_queue(monkeypatch):
    monkeypatch.setattr(RunQueue, "_loop", lambda self: self._stop.wait())


@pytest.fixture
def reference_client(stopped_queue, client):
    return client


def create_run(client, scene):
    return client.post("/api/runs", json={"scene_id": scene["id"],
        "network": {"asset_id": "net-001", "version": "1.0.0"}, "origin": "S", "destination": "T", "blocked_edges": []})


def fingerprint(identity):
    return {path.relative_to(FILES_DIR / identity).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (FILES_DIR / identity).rglob("*") if path.is_file()}


def test_mixed_references_keep_complete_details_but_count_each_owner_once(reference_client):
    client = reference_client
    layer = upload(client).json()
    identity = layer["asset_id"]
    with SessionLocal() as session:
        first = session.get(AssetVersion, (identity, "1.0.0"))
        session.add(AssetVersion(asset_id=identity, version="2.0.0", entry_url=first.entry_url,
            byte_size=first.byte_size, file_count=first.file_count, sha256=first.sha256,
            file_manifest=deepcopy(first.file_manifest), bounds=deepcopy(first.bounds)))
        session.commit()
    old, new = layer_state(layer), layer_state(layer)
    new.update(layer_id="other-version", order=4, asset={"asset_id": identity, "version": "2.0.0"})
    scene = client.post("/api/scenes", json={**draft(), "layers": [old, new]}).json()
    run = create_run(client, scene).json()
    before = fingerprint(identity)
    response = client.delete(f"/api/assets/{identity}")
    assert response.status_code == 409, response.text
    conflict = response.json()
    assert conflict["code"] == "ASSET_IN_USE"
    assert conflict["message"] == "资产仍被 1 个图层、1 个场景、1 个历史运行引用"
    expected = [{"id": layer["id"], "name": layer["name"]}]
    expected += [{"type": kind, "id": record["id"] if kind == "scene" else record["run_id"],
                  "name": scene["name"], "version": scene["version"], "asset_version": version}
                 for kind, record in [("scene", scene), ("run", run)] for version in ["1.0.0", "2.0.0"]]
    assert conflict["detail"]["references"] == expected
    assert conflict["detail"]["reference_count"] == 5
    assert conflict["detail"]["message"] == conflict["message"]
    assert client.get(f"/api/assets/{identity}").json()["references"] == expected
    assert fingerprint(identity) == before


@pytest.mark.parametrize("terminal", ["cancelled", "failed", "succeeded"])
@pytest.mark.parametrize("release_scene", ["unlink", "delete"])
def test_terminal_history_still_protects_files_after_live_references_release(reference_client, terminal, release_scene):
    client = reference_client
    layer = upload(client).json()
    identity = layer["asset_id"]
    scene = client.post("/api/scenes", json={**draft(), "layers": [layer_state(layer)]}).json()
    run = create_run(client, scene).json()
    if terminal == "cancelled":
        assert client.post(f"/api/runs/{run['run_id']}/cancel").status_code == 200
    else:
        assert claim_next() == run["run_id"]
        if terminal == "failed":
            finish_run(run["run_id"], "failed", error={"code": "MODEL_ERROR", "message": "回归测试失败终态", "detail": None})
        else:
            path = {"path": [], "length_m": None, "duration_s": None, "reachable": False}
            finish_run(run["run_id"], "succeeded", result={"run_id": run["run_id"], "baseline": path, "blocked": path,
                "metrics": {"increase_percent": None, "rerouted": False}, "created_at": datetime.now(timezone.utc).isoformat()})
    assert client.get(f"/api/runs/{run['run_id']}").json()["status"] == terminal
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    if release_scene == "unlink":
        response = client.put(f"/api/scenes/{scene['id']}", json={**draft(), "layers": []}, headers={"If-Match": '"1"'})
        assert response.status_code == 200, response.text
    else:
        assert client.delete(f"/api/scenes/{scene['id']}", headers={"If-Match": '"1"'}).status_code == 204
    before = fingerprint(identity)
    response = client.delete(f"/api/assets/{identity}")
    assert response.status_code == 409, response.text
    conflict = response.json()
    assert conflict["code"] == "ASSET_IN_USE"
    assert conflict["message"] == "资产仍被 0 个图层、0 个场景、1 个历史运行引用"
    assert conflict["detail"]["references"] == [{"type": "run", "id": run["run_id"], "name": scene["name"],
        "version": 1, "asset_version": "1.0.0"}]
    assert conflict["detail"]["reference_count"] == 1
    assert client.get(f"/api/runs/{run['run_id']}/input").json()["scene"]["layers"] == [layer_state(layer)]
    assert fingerprint(identity) == before


def test_default_files_are_protected_and_external_deletion_only_removes_registration(reference_client):
    client = reference_client
    with SessionLocal() as session:
        ensure_builtin_assets(session)
        session.commit()
    identity = builtin_asset_id("university-town", "demo-points")
    root, manifest, _ = builtin_asset_files(identity, "/samples/university-town/water-points.geojson")
    before_default = {item["path"]: hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() for item in manifest}
    protected = client.delete(f"/api/assets/{identity}")
    assert protected.status_code == 403 and protected.json()["code"] == "ASSET_PROTECTED"
    assert before_default == {item["path"]: hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() for item in manifest}
    assert client.get(f"/api/assets/{identity}").status_code == 200
    local = upload(client).json()
    before_local = fingerprint(local["asset_id"])
    before_folders = set(FILES_DIR.iterdir())
    url = "https://example.invalid/immutable-source/data.geojson"
    registered = client.post("/api/assets/register", json={"name": "外部登记", "type": "geojson", "location": url})
    assert registered.status_code == 201, registered.text
    external = registered.json()
    assert external["source_kind"] == "external" and external["entry_url"] == url
    layer = client.post("/api/layers", json={"name": "外部图层", "category": "专题", "type": "geojson", "url": url, "source": "外部"}).json()
    assert client.delete(f"/api/assets/{external['asset_id']}").json()["detail"]["references"] == [{"id": layer["id"], "name": layer["name"]}]
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    assert client.delete(f"/api/assets/{external['asset_id']}").status_code == 204
    assert client.get(f"/api/assets/{external['asset_id']}").status_code == 404
    assert set(FILES_DIR.iterdir()) == before_folders
    assert fingerprint(local["asset_id"]) == before_local


@pytest.mark.parametrize("owner", ["scene", "run"])
@pytest.mark.parametrize("first_writer", ["create", "delete"])
def test_reference_creation_and_asset_delete_compete_with_real_write_transactions(reference_client, monkeypatch, owner, first_writer):
    client = reference_client
    layer = upload(client).json()
    identity = layer["asset_id"]
    body = {**draft(), "layers": [layer_state(layer)]}
    scene = client.post("/api/scenes", json=body).json() if owner == "run" else None
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    before = fingerprint(identity)
    holding, competing, release = Event(), Event(), Event()
    module = scenes if owner == "scene" else runs
    create_writer, delete_writer = module.reserve_writer, assets.lock_catalog

    def write(session, action, original):
        if action == first_writer:
            original(session)
            holding.set()
            assert release.wait(5), "测试须释放已持有的真实SQLite写事务"
        else:
            competing.set()
            original(session)

    monkeypatch.setattr(module, "reserve_writer", lambda session: write(session, "create", create_writer))
    monkeypatch.setattr(assets, "lock_catalog", lambda session: write(session, "delete", delete_writer))

    def create():
        return client.post("/api/scenes", json=body) if owner == "scene" else create_run(client, scene)

    operations = {"create": create, "delete": lambda: client.delete(f"/api/assets/{identity}")}
    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(operations[first_writer])
        try:
            assert holding.wait(5), "首个请求应持有写事务"
            follower = pool.submit(operations["delete" if first_writer == "create" else "create"])
            assert competing.wait(5), "另一HTTP请求应已开始争用同一写事务"
        finally:
            release.set()
        outcomes = {first_writer: leader.result(timeout=10),
                    "delete" if first_writer == "create" else "create": follower.result(timeout=10)}
    if owner == "scene" and first_writer == "delete":
        assert outcomes["delete"].status_code == 204, outcomes["delete"].text
        assert outcomes["create"].status_code == 422, outcomes["create"].text
        assert client.get(f"/api/assets/{identity}").status_code == 404
        assert not (FILES_DIR / identity).exists()
    else:
        assert outcomes["create"].status_code == 201, outcomes["create"].text
        assert outcomes["delete"].status_code == 409, outcomes["delete"].text
        assert outcomes["delete"].json()["code"] == "ASSET_IN_USE"
        assert fingerprint(identity) == before
        assert client.get(f"/api/assets/{identity}").status_code == 200
    with SessionLocal() as session:
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_historical_run_keeps_its_network_version_foreign_key_after_scene_delete(reference_client):
    client = reference_client
    scene = client.post("/api/scenes", json=draft()).json()
    run = create_run(client, scene).json()
    assert client.post(f"/api/runs/{run['run_id']}/cancel").status_code == 200
    assert client.delete(f"/api/scenes/{scene['id']}", headers={"If-Match": '"1"'}).status_code == 204
    with SessionLocal() as session:
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            session.execute(delete(NetworkVersion).where(NetworkVersion.asset_id == "net-001", NetworkVersion.version == "1.0.0"))
            session.commit()
        session.rollback()
        assert session.get(NetworkVersion, ("net-001", "1.0.0")) is not None
    assert client.get(f"/api/runs/{run['run_id']}/input").status_code == 200

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
import json

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Asset, AssetVersion, NetworkVersion, Scene, SceneAssetReference
from app.networks import publish_network
from sqlalchemy import update
from sqlalchemy.orm import Session
from test_layers import GEO, TILESET, upload as upload_layer, zip_data


def upload(client):
    return upload_layer(client, json.dumps(GEO).encode())


def draft():
    return {"name": "演示场景", "camera": {"longitude": 113.36, "latitude": 23.04, "height": 800,
             "heading": 0.2, "pitch": -0.9, "roll": 0.1, "scene_mode": "3d"},
            "layers": [], "network": {"asset_id": "net-001", "version": "1.0.0"},
            "origin": "S", "destination": "T", "blocked_edges": ["B-T"], "params": {"mode": "car"},
            "seed": 14, "current_time": "2026-10-26T10:00:00+08:00", "run_id": None}


def layer_state(layer):
    return {"layer_id": layer["id"], "asset": {"asset_id": layer["asset_id"], "version": layer["asset_version"]},
            "map_attached": True, "map_visible": False, "map_opacity": 0.4, "road_max_level": 2, "order": 3}


def test_tiles_height_settings_persist_and_full_scene_pins_placement(client):
    archive = zip_data({"tileset.json": json.dumps(TILESET), "nested/content.glb": b"model"})
    layer = upload_layer(client, archive, "3dtiles", "city.zip").json()
    assert layer["tiles_height_offset_m"] == 0 and layer["tiles_ground_anchor"] is None
    assert layer["tiles_align_to_terrain"] is None
    endpoint = f"/api/layers/catalog/{layer['id']}/map-state"
    placement = {"tiles_height_offset_m": -2.5, "tiles_align_to_terrain": True,
                 "tiles_ground_anchor": {"longitude": 113.36, "latitude": 23.04, "height": 30}}
    assert client.patch(endpoint, json={**placement, "tiles_ground_anchor": {"longitude": 181, "latitude": 23, "height": 30}}).status_code == 422
    assert client.patch(endpoint, json={"tiles_height_offset_m": None}).status_code == 422
    updated = client.patch(endpoint, json=placement)
    assert updated.status_code == 200, updated.text
    assert {key: updated.json()[key] for key in placement} == placement
    assert client.patch(endpoint, json={"map_visible": False}).json()["tiles_ground_anchor"] == placement["tiles_ground_anchor"]
    scene = client.post("/api/scenes", json={**draft(), "layers": [{**layer_state(layer), **placement}]})
    assert scene.status_code == 201, scene.text
    scene_id = scene.json()["id"]
    cleared = client.patch(f"/api/layers/{layer['id']}/map-state",
                           json={"tiles_ground_anchor": None, "tiles_align_to_terrain": False})
    assert cleared.json()["tiles_ground_anchor"] is None
    with TestClient(app) as restarted:
        saved = restarted.get(f"/api/scenes/{scene_id}").json()["layers"][0]
        assert {key: saved[key] for key in placement} == placement
        assert restarted.get("/api/layers").json()[0]["tiles_height_offset_m"] == -2.5
        assert restarted.get("/api/layers").json()[0]["tiles_align_to_terrain"] is False
    auto = {"tiles_align_to_terrain": True, "tiles_ground_anchor": None, "tiles_height_offset_m": 0}
    scene = client.post("/api/scenes", json={**draft(), "layers": [{**layer_state(layer), **auto}]})
    assert scene.status_code == 201, scene.text
    assert {key: scene.json()["layers"][0][key] for key in auto} == auto
    copied_legacy = client.post("/api/scenes", json={**draft(), "layers": [layer_state(layer)]})
    assert copied_legacy.status_code == 201, copied_legacy.text
    assert copied_legacy.json()["layers"][0]["tiles_align_to_terrain"] is False


def test_builtin_tiles_placement_follows_its_campus_asset(client):
    url = "/api/layers/catalog/demo-buildings/map-state"
    anchor = {"longitude": 113.36, "latitude": 23.04, "height": 12}
    saved = client.patch(url, params={"campus": "university-town"}, json={
        "tiles_height_offset_m": 3, "tiles_ground_anchor": anchor, "tiles_align_to_terrain": False,
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["tiles_ground_anchor"] == anchor
    other = client.patch(url, params={"campus": "huangpu"}, json={"tiles_height_offset_m": -1})
    assert other.json()["tiles_ground_anchor"] is None
    assert other.json()["tiles_align_to_terrain"] is None
    assert other.json()["tiles_height_offset_m"] == -1
    rows = client.get("/api/layers/catalog", params={"campus": "university-town"}).json()
    first = next(row for row in rows if row["id"] == "demo-buildings")
    assert first["tiles_ground_anchor"] == anchor and first["tiles_height_offset_m"] == 3
    assert first["tiles_align_to_terrain"] is False


def test_create_get_restart_and_full_config_restore(client):
    layer = upload(client).json()
    data = draft()
    data["layers"] = [layer_state(layer)]
    response = client.post("/api/scenes", json=data)
    assert response.status_code == 201
    scene = response.json()
    assert response.headers["etag"] == '"1"'
    assert scene["version"] == 1 and scene["id"]
    assert scene["current_time"] == "2026-10-26T02:00:00Z"
    assert scene["created_at"].endswith("Z") and scene["updated_at"].endswith("Z")
    for key in data.keys() - {"current_time"}:
        assert scene[key] == data[key]
    fetched = client.get(f"/api/scenes/{scene['id']}")
    assert fetched.json() == scene and fetched.headers["etag"] == '"1"'
    assert client.get("/api/layers").json()[0]["map_visible"] is True
    with TestClient(app) as restarted:
        assert restarted.get(f"/api/scenes/{scene['id']}").json() == scene


def test_update_replaces_snapshot_increments_etag_and_preserves_creation_time(client):
    scene = client.post("/api/scenes", json=draft()).json()
    changed = draft()
    changed.update(name="修改后", network=None, origin=None, destination=None, blocked_edges=[], seed=0,
                   current_time=None, camera={**changed["camera"], "scene_mode": "2d"})
    response = client.put(f"/api/scenes/{scene['id']}", json=changed, headers={"If-Match": '"1"'})
    assert response.status_code == 200
    assert response.headers["etag"] == '"2"'
    result = response.json()
    assert result["created_at"] == scene["created_at"]
    assert result["updated_at"] >= scene["updated_at"]
    assert result["version"] == 2
    for key, value in changed.items():
        assert result[key] == value
    stale = client.put(f"/api/scenes/{scene['id']}", json=draft(), headers={"If-Match": '"1"'})
    assert stale.status_code == 409 and stale.json()["code"] == "SCENE_VERSION_CONFLICT"
    assert client.get(f"/api/scenes/{scene['id']}").json() == result


@pytest.mark.parametrize("header", [None, "1", 'W/"1"', '"0"', '*', '"1", "2"', '"abc"', '"' + '9' * 4500 + '"'])
def test_if_match_requires_one_quoted_positive_version(client, header):
    scene = client.post("/api/scenes", json=draft()).json()
    headers = {} if header is None else {"If-Match": header}
    for method in ["put", "delete"]:
        response = getattr(client, method)(f"/api/scenes/{scene['id']}", headers=headers,
                                           **({"json": draft()} if method == "put" else {}))
        assert response.status_code == 400
        assert response.json()["trace_id"] == response.headers["x-trace-id"]
    assert client.get(f"/api/scenes/{scene['id']}").json()["version"] == 1


def test_scene_catalog_pagination_unknown_and_confirmed_delete(client):
    ids = [client.post("/api/scenes", json={**draft(), "name": str(index)}).json()["id"] for index in range(3)]
    rows = client.get("/api/scenes?page_size=2").json()
    later = client.get("/api/scenes?page_size=2&page=2").json()
    assert rows["total"] == 3 and set(ids) == {item["id"] for item in rows["items"] + later["items"]}
    for search in (ids[1], " 1 "):
        found = client.get("/api/scenes", params={"q": search, "page_size": 1}).json()
        assert found["total"] == 1 and found["items"][0]["id"] == ids[1]
    assert client.get("/api/scenes", params={"q": "%"}).json()["total"] == 0
    assert client.get("/api/scenes?page=9999999999999999999999999").json()["items"] == []
    for query in ["page=0", "page_size=101"]:
        assert client.get("/api/scenes?" + query).status_code == 422
    assert client.get("/api/scenes/missing").json()["code"] == "SCENE_NOT_FOUND"
    assert client.delete(f"/api/scenes/{ids[0]}", headers={"If-Match": '"2"'}).status_code == 409
    assert client.delete(f"/api/scenes/{ids[0]}", headers={"If-Match": '"1"'}).status_code == 204
    assert client.get(f"/api/scenes/{ids[0]}").status_code == 404


@pytest.mark.parametrize("change,code", [
    ({"network": {"asset_id": "missing", "version": "1"}}, "NETWORK_NOT_FOUND"),
    ({"network": {"asset_id": "net-001", "version": "missing"}}, "NETWORK_NOT_FOUND"),
    ({"origin": "missing"}, "INVALID_NODE"), ({"destination": "missing"}, "INVALID_NODE"),
    ({"blocked_edges": ["T-B"]}, "INVALID_EDGE"), ({"network": None}, "NETWORK_REQUIRED"),
    ({"run_id": "missing"}, "RUN_NOT_FOUND"),
    ({"layers": [{"layer_id": "missing", "asset": {"asset_id": "missing", "version": "1"},
                  "map_attached": True, "map_visible": True, "map_opacity": 1, "order": 0}]}, "ASSET_VERSION_NOT_FOUND"),
])
def test_invalid_references_do_not_create_partial_scene(client, change, code):
    response = client.post("/api/scenes", json={**draft(), **change})
    assert response.status_code == 422 and response.json()["code"] == code
    assert client.get("/api/scenes").json()["total"] == 0
    with SessionLocal() as session:
        assert session.query(SceneAssetReference).count() == 0


def test_scene_pins_original_version_and_references_release_on_replace_or_delete(client):
    layer = upload(client).json()
    data = draft()
    data["layers"] = [layer_state(layer)]
    scene = client.post("/api/scenes", json=data).json()
    client.delete(f"/api/layers/{layer['id']}")
    asset = client.get(f"/api/assets/{layer['asset_id']}").json()
    assert asset["reference_count"] == 1
    assert asset["references"][0] == {"type": "scene", "id": scene["id"], "name": data["name"],
                                        "version": 1, "asset_version": "1.0.0"}
    assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 409
    # The saved binding remains meaningful after its global registration is removed.
    response = client.put(f"/api/scenes/{scene['id']}", json={**data, "name": "保留旧绑定"}, headers={"If-Match": '"1"'})
    assert response.status_code == 200 and response.json()["layers"] == data["layers"]
    response = client.put(f"/api/scenes/{scene['id']}", json={**data, "layers": []}, headers={"If-Match": '"2"'})
    assert response.status_code == 200
    assert client.get(f"/api/assets/{layer['asset_id']}").json()["references"] == []
    data["layers"] = [layer_state(layer)]
    assert client.put(f"/api/scenes/{scene['id']}", json=data, headers={"If-Match": '"3"'}).status_code == 200
    assert client.delete(f"/api/scenes/{scene['id']}", headers={"If-Match": '"4"'}).status_code == 204
    assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 204


def test_duplicate_layers_invalid_basemap_and_unavailable_assets_rejected(client):
    layer = upload(client).json()
    data = draft()
    data["layers"] = [layer_state(layer)] * 2
    assert client.post("/api/scenes", json=data).status_code == 422
    data["layers"] = [{**layer_state(layer), "layer_id": "basemap"}]
    assert client.post("/api/scenes", json=data).status_code == 422
    data["layers"] = [{**layer_state(layer), "asset": None}]
    assert client.post("/api/scenes", json=data).status_code == 422
    with SessionLocal() as session:
        from app.models import Asset
        session.get(Asset, layer["asset_id"]).status = "deleting"
        session.commit()
    data["layers"] = [layer_state(layer)]
    assert client.post("/api/scenes", json=data).json()["code"] == "ASSET_UNAVAILABLE"


def test_scene_names_times_unknown_fields_and_normalized_blocked_edges(client):
    for change in [{"name": "  "}, {"current_time": "2026-10-26T10:00:00"}, {"unknown": "ignored?"}]:
        assert client.post("/api/scenes", json={**draft(), **change}).status_code == 422
    data = draft()
    data["blocked_edges"] = ["B-T", "A-B", "B-T"]
    result = client.post("/api/scenes", json=data).json()
    assert result["blocked_edges"] == ["A-B", "B-T"]
    empty = {**draft(), "network": None, "origin": None, "destination": None, "blocked_edges": []}
    assert client.post("/api/scenes", json=empty).status_code == 201


def test_two_updates_with_same_version_have_one_winner(client):
    scene = client.post("/api/scenes", json=draft()).json()
    barrier = Barrier(2)

    def update(name):
        barrier.wait(timeout=5)
        return client.put(f"/api/scenes/{scene['id']}", json={**draft(), "name": name}, headers={"If-Match": '"1"'})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update, name) for name in ["one", "two"]]
        results = [future.result(timeout=10) for future in futures]
    assert sorted(response.status_code for response in results) == [200, 409]
    winner = next(response.json() for response in results if response.status_code == 200)
    assert client.get(f"/api/scenes/{scene['id']}").json() == winner


def test_failed_update_preserves_previous_snapshot_version_and_references(client):
    layer = upload(client).json()
    data = draft()
    data["layers"] = [layer_state(layer)]
    scene = client.post("/api/scenes", json=data).json()
    failed = deepcopy(data)
    failed["layers"][0]["asset"]["version"] = "unknown"
    assert client.put(f"/api/scenes/{scene['id']}", json=failed, headers={"If-Match": '"1"'}).status_code == 422
    assert client.get(f"/api/scenes/{scene['id']}").json() == scene
    assert client.get(f"/api/assets/{layer['asset_id']}").json()["reference_count"] == 2


def test_update_response_is_its_own_committed_snapshot_when_a_new_writer_follows(client, monkeypatch):
    scene = client.post("/api/scenes", json=draft()).json()
    original_commit = Session.commit

    def commit_then_compete(session):
        should_compete = any(isinstance(record, Scene) and record.document["name"] == "our update"
                             for record in session.identity_map.values())
        original_commit(session)
        if should_compete:
            with SessionLocal() as peer:
                peer.execute(update(Scene).where(Scene.id == scene["id"])
                             .values(version=3, document={**draft(), "name": "newer update"}))
                original_commit(peer)

    monkeypatch.setattr(Session, "commit", commit_then_compete)
    response = client.put(f"/api/scenes/{scene['id']}", json={**draft(), "name": "our update"}, headers={"If-Match": '"1"'})
    assert response.status_code == 200 and response.headers["etag"] == '"2"'
    assert response.json()["version"] == 2 and response.json()["name"] == "our update"
    assert client.get(f"/api/scenes/{scene['id']}").json()["version"] == 3


def test_scene_keeps_pinned_asset_and_network_after_newer_versions_publish(client):
    layer = upload(client).json()
    data = draft()
    data["layers"] = [layer_state(layer)]
    scene = client.post("/api/scenes", json=data).json()
    with SessionLocal() as session:
        asset = session.get(Asset, layer["asset_id"])
        original = session.get(AssetVersion, (asset.id, "1.0.0"))
        session.add(AssetVersion(asset_id=asset.id, version="2.0.0", entry_url=original.entry_url,
                                 byte_size=original.byte_size, file_count=original.file_count))
        asset.current_version = "2.0.0"
        updated = deepcopy(session.get(NetworkVersion, ("net-001", "1.0.0")).document)
        updated["version"] = "2.0.0"
        publish_network(session, updated)
        session.commit()
    try:
        assert client.get("/api/networks/net-001").json()["version"] == "2.0.0"
        assert client.get(f"/api/scenes/{scene['id']}").json() == scene
        response = client.put(f"/api/scenes/{scene['id']}", json={**data, "name": "仍用旧版本"}, headers={"If-Match": '"1"'})
        assert response.status_code == 200
        assert response.json()["layers"][0]["asset"]["version"] == "1.0.0"
        assert response.json()["network"]["version"] == "1.0.0"
    finally:
        with SessionLocal() as session:
            session.delete(session.get(NetworkVersion, ("net-001", "2.0.0")))
            session.commit()

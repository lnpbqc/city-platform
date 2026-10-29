from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from threading import Event

import pytest
from sqlalchemy import func, select

from app import main, scenes
from app.database import FILES_DIR, SessionLocal
from app.models import Bookmark
from test_runs import paused_queue, queued_client, setup_run
from test_scenes import draft, layer_state, upload


def workspace(scene, **changes):
    return {"page": "map", "scene_id": scene["id"], "scene_version": scene["version"],
            "run_id": scene["run_id"], "time": "2026-10-25T08:00:00+08:00", "resolution": "day",
            "camera": deepcopy(scene["camera"]), "comparison": {"time": "2026-10-26T09:00:00+08:00", "resolution": "hour"}, **changes}


def save_bookmark(client, state, **changes):
    return client.post("/api/bookmarks", json={"name": "工作区收藏", "kind": "scene", "state": state, **changes})


def file_hashes():
    return {path.relative_to(FILES_DIR).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in FILES_DIR.rglob("*") if path.is_file()}


def test_legacy_bookmark_shapes_defaults_and_existing_crud_remain_compatible(client):
    for body in ({"name": "地区", "kind": "region", "region_id": "440100"},
                 {"name": "点位", "kind": "point", "longitude": 0, "latitude": 0, "state": None}):
        response = client.post("/api/bookmarks", json=body)
        assert response.status_code == 201, response.text
        item = response.json()
        assert set(item) == {"id", "name", "kind", "region_id", "longitude", "latitude", "created_at", "state"}
        assert item["state"] is None and item["created_at"].endswith("Z")
        assert client.patch(f"/api/bookmarks/{item['id']}", json={"name": "改名"}).json() == {**item, "name": "改名"}
    assert len(client.get("/api/bookmarks").json()) == 2


def test_full_workspace_state_is_utc_json_and_rename_does_not_change_the_snapshot(client):
    scene = client.post("/api/scenes", json=draft()).json()
    response = save_bookmark(client, workspace(scene))
    assert response.status_code == 201, response.text
    item = response.json()
    expected = {**workspace(scene), "time": "2026-10-25T00:00:00Z",
                "comparison": {"time": "2026-10-26T01:00:00Z", "resolution": "hour"}}
    assert item["state"] == expected
    assert item["region_id"] is item["longitude"] is item["latitude"] is None
    with SessionLocal() as session:
        assert session.get(Bookmark, item["id"]).state == expected
    renamed = client.patch(f"/api/bookmarks/{item['id']}", json={"name": "  新名称  "})
    assert renamed.status_code == 200 and renamed.json() == {**item, "name": "新名称"}
    assert client.patch(f"/api/bookmarks/{item['id']}", json={"name": "不能替换", "state": {}}).status_code == 422
    assert client.get("/api/bookmarks").json() == [{**item, "name": "新名称"}]
    assert client.delete(f"/api/bookmarks/{item['id']}").status_code == 204
    assert client.get(f"/api/scenes/{scene['id']}").json() == scene


def test_simulation_workspace_accepts_null_times_and_default_hour_resolution(client):
    scene = client.post("/api/scenes", json=draft()).json()
    state = workspace(scene, page="simulation", comparison=None, time=None)
    state.pop("resolution")
    response = save_bookmark(client, state)
    assert response.status_code == 201, response.text
    assert response.json()["state"] == {**state, "resolution": "hour"}


@pytest.mark.parametrize("changes", [
    {"state": None}, {"state": {}}, {"region_id": "440100"}, {"longitude": 0}, {"latitude": 0},
    {"kind": "region", "region_id": "440100"}, {"kind": "point", "longitude": 0, "latitude": 0},
])
def test_workspace_and_legacy_location_fields_cannot_mix(client, changes):
    state = workspace({"id": "scene", "version": 1, "run_id": None, "camera": draft()["camera"]})
    response = client.post("/api/bookmarks", json={"name": "错误收藏", "kind": "scene", "state": state, **changes})
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"
    assert client.get("/api/bookmarks").json() == []


@pytest.mark.parametrize("changes", [
    {"page": "other"}, {"scene_id": ""}, {"scene_id": "   "}, {"scene_version": 0}, {"scene_version": 1.5},
    {"time": "2026-10-25T08:00:00"}, {"resolution": "minute"}, {"extra": "not allowed"},
    {"comparison": {"time": "2026-10-25T00:00:00", "resolution": "hour"}},
    {"comparison": {"time": "2026-10-25T00:00:00Z", "resolution": "hour", "extra": 1}},
    {"comparison": {"time": "2026-10-25T00:00:00Z", "resolution": "minute"}},
    {"page": "simulation"}, {"camera": {**draft()["camera"], "height": "NaN"}},
    {"time": "9999-12-31T23:00:00-10:00"},
])
def test_workspace_state_validates_time_camera_versions_and_unknown_fields(client, changes):
    state = workspace({"id": "scene", "version": 1, "run_id": None, "camera": draft()["camera"]}, **changes)
    response = save_bookmark(client, state)
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR", response.text
    assert response.json()["trace_id"] == response.headers["x-trace-id"]
    assert client.get("/api/bookmarks").json() == []


@pytest.mark.parametrize("changes,status,code", [
    ({"scene_id": "missing"}, 404, "SCENE_NOT_FOUND"),
    ({"scene_version": 2}, 409, "SCENE_VERSION_CONFLICT"),
    ({"run_id": "missing"}, 422, "RUN_NOT_FOUND"),
])
def test_reference_failures_never_create_bookmarks_and_include_trace(client, changes, status, code):
    scene = client.post("/api/scenes", json=draft()).json()
    response = save_bookmark(client, workspace(scene, **changes))
    assert response.status_code == status and response.json()["code"] == code, response.text
    assert response.json()["trace_id"] == response.headers["x-trace-id"]
    if code == "SCENE_VERSION_CONFLICT":
        assert response.json()["detail"]["current_version"] == 1
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Bookmark)) == 0


def test_historical_run_may_reference_a_captured_scene_but_its_state_run_must_match(queued_client):
    client = queued_client
    request = setup_run(client)
    run = client.post("/api/runs", json=request).json()
    original = client.get(f"/api/scenes/{request['scene_id']}").json()
    response = save_bookmark(client, workspace(original, run_id=run["run_id"]))
    assert response.status_code == 422 and response.json()["code"] == "SCENE_RUN_MISMATCH"
    captured = client.post("/api/scenes", json={**draft(), "run_id": run["run_id"]}).json()
    assert captured["id"] != run["scene_id"]
    mismatch = save_bookmark(client, workspace(captured, run_id=None))
    assert mismatch.status_code == 422 and mismatch.json()["code"] == "SCENE_RUN_MISMATCH"
    response = save_bookmark(client, workspace(captured, page="simulation", comparison=None))
    assert response.status_code == 201, response.text
    assert client.delete(f"/api/bookmarks/{response.json()['id']}").status_code == 204
    assert client.get(f"/api/scenes/{captured['id']}").json() == captured
    assert client.get(f"/api/runs/{run['run_id']}").json() == run


def test_scene_version_reads_reject_stale_urls_and_dead_bookmarks_remain_listed(client):
    scene = client.post("/api/scenes", json=draft()).json()
    item = save_bookmark(client, workspace(scene)).json()
    endpoint = f"/api/scenes/{scene['id']}"
    valid = client.get(endpoint, params={"version": 1})
    assert valid.status_code == 200 and valid.json() == scene and valid.headers["etag"] == '"1"'
    updated = client.put(endpoint, json={**draft(), "name": "已变更"}, headers={"If-Match": '"1"'}).json()
    stale = client.get(endpoint, params={"version": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "SCENE_VERSION_CONFLICT"
    assert stale.json()["detail"]["current_version"] == 2
    assert client.get(endpoint).json() == updated
    assert client.get(endpoint, params={"version": 2}).headers["etag"] == '"2"'
    assert client.get("/api/bookmarks").json() == [item]
    assert client.delete(endpoint, headers={"If-Match": '"2"'}).status_code == 204
    assert client.get(endpoint, params={"version": 1}).json()["code"] == "SCENE_NOT_FOUND"
    assert client.get("/api/bookmarks").json() == [item]
    assert client.delete(f"/api/bookmarks/{item['id']}").status_code == 204


@pytest.mark.parametrize("version", [0, -1, "not-a-version", 1.5])
def test_scene_version_query_is_a_positive_integer(client, version):
    scene = client.post("/api/scenes", json=draft()).json()
    response = client.get(f"/api/scenes/{scene['id']}", params={"version": version})
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"


def test_deleting_bookmark_keeps_its_scene_asset_references_and_all_files(client):
    layer = upload(client).json()
    scene = client.post("/api/scenes", json={**draft(), "layers": [layer_state(layer)]}).json()
    before = file_hashes()
    item = save_bookmark(client, workspace(scene)).json()
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    assert client.delete(f"/api/bookmarks/{item['id']}").status_code == 204
    assert client.delete(f"/api/assets/{layer['asset_id']}").json()["code"] == "ASSET_IN_USE"
    assert file_hashes() == before


@pytest.mark.parametrize("first_writer", ["bookmark", "scene"])
def test_bookmark_validation_and_scene_update_compete_in_one_real_write_transaction(queued_client, monkeypatch, first_writer):
    client = queued_client
    scene = client.post("/api/scenes", json=draft()).json()
    holding, competing, release = Event(), Event(), Event()
    original_bookmark, original_scene = main.reserve_writer, scenes.reserve_writer

    def reserve(session, action, original):
        if action == first_writer:
            original(session)
            holding.set()
            assert release.wait(5)
        else:
            competing.set()
            original(session)

    monkeypatch.setattr(main, "reserve_writer", lambda session: reserve(session, "bookmark", original_bookmark))
    monkeypatch.setattr(scenes, "reserve_writer", lambda session: reserve(session, "scene", original_scene))
    operations = {"bookmark": lambda: save_bookmark(client, workspace(scene)),
                  "scene": lambda: client.put(f"/api/scenes/{scene['id']}", json={**draft(), "name": "并发更新"}, headers={"If-Match": '"1"'})}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(operations[first_writer])
        assert holding.wait(5)
        second = pool.submit(operations["scene" if first_writer == "bookmark" else "bookmark"])
        try:
            assert competing.wait(5)
        finally:
            release.set()
        first_result, second_result = first.result(timeout=10), second.result(timeout=10)
    bookmark = first_result if first_writer == "bookmark" else second_result
    updated = second_result if first_writer == "bookmark" else first_result
    assert updated.status_code == 200
    assert bookmark.status_code == (201 if first_writer == "bookmark" else 409), bookmark.text
    assert len(client.get("/api/bookmarks").json()) == (1 if first_writer == "bookmark" else 0)

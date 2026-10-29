from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.database import SessionLocal
from app.models import Run
from app.run_artifacts import RUNS_DIR
from test_runs import paused_queue, queued_client, setup_run, wait_terminal
from test_scenes import draft, layer_state, upload


@pytest.mark.parametrize("scene_change", ["changed", "deleted"])
def test_rerun_keeps_old_snapshot_hash_and_asset_references_after_scene_changes(queued_client, scene_change):
    client = queued_client
    layer = upload(client).json()
    body = {**draft(), "layers": [layer_state(layer)]}
    scene = client.post("/api/scenes", json=body).json()
    request = {**setup_run(client), "scene_id": scene["id"]}
    original = client.post("/api/runs", json=request).json()
    saved = client.get(f"/api/runs/{original['run_id']}/input").json()
    old_file = (RUNS_DIR / original["run_id"] / "input.json").read_bytes()
    if scene_change == "changed":
        assert client.put(f"/api/scenes/{scene['id']}", json={**body, "layers": [], "seed": 987}, headers={"If-Match": '"1"'}).status_code == 200
    else:
        assert client.delete(f"/api/scenes/{scene['id']}", headers={"If-Match": '"1"'}).status_code == 204
    client.delete(f"/api/layers/{layer['id']}")
    response = client.post(f"/api/runs/{original['run_id']}/rerun", headers={"Idempotency-Key": "fixed-old-input"})
    assert response.status_code == 201, response.text
    rerun = response.json()
    assert rerun["run_id"] != original["run_id"] and rerun["trace_id"] == response.headers["x-trace-id"]
    assert rerun["trace_id"] != original["trace_id"]
    for field in ["inputs_sha256", "scene_id", "scene_version", "model_version", "data_version"]:
        assert rerun[field] == original[field]
    assert client.get(f"/api/runs/{rerun['run_id']}/input").json() == saved
    again = client.post(f"/api/runs/{original['run_id']}/rerun", headers={"Idempotency-Key": "fixed-old-input"})
    assert again.status_code == 200 and again.json() == rerun
    if scene_change == "changed":
        assert client.delete(f"/api/scenes/{scene['id']}", headers={"If-Match": '"2"'}).status_code == 204
    conflict = client.delete(f"/api/assets/{layer['asset_id']}")
    assert conflict.status_code == 409 and conflict.json()["code"] == "ASSET_IN_USE"
    references = conflict.json()["detail"]["references"]
    assert {(item["type"], item["id"], item["asset_version"]) for item in references} == {
        ("run", original["run_id"], "1.0.0"), ("run", rerun["run_id"], "1.0.0")}
    assert (RUNS_DIR / original["run_id"] / "input.json").read_bytes() == old_file


def test_rerun_new_keys_and_global_idempotency_conflicts(queued_client):
    client = queued_client
    body = setup_run(client)
    original = client.post("/api/runs", json=body).json()
    other = client.post("/api/runs", json={**body, "seed": 1}).json()
    path = f"/api/runs/{original['run_id']}/rerun"
    first = client.post(path, headers={"Idempotency-Key": "shared-key"}).json()
    second = client.post(path, headers={"Idempotency-Key": "another-key"}).json()
    third = client.post(path).json()
    assert len({original["run_id"], first["run_id"], second["run_id"], third["run_id"]}) == 4
    assert {first["inputs_sha256"], second["inputs_sha256"], third["inputs_sha256"]} == {original["inputs_sha256"]}
    conflict = client.post(f"/api/runs/{other['run_id']}/rerun", headers={"Idempotency-Key": "shared-key"})
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert client.get("/api/runs").json()["total"] == 5


def test_five_concurrent_reruns_with_one_key_create_one_record(queued_client):
    client = queued_client
    original = client.post("/api/runs", json=setup_run(client)).json()
    barrier = Barrier(5)

    def replay():
        barrier.wait(timeout=5)
        return client.post(f"/api/runs/{original['run_id']}/rerun", headers={"Idempotency-Key": "five-retries"})

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = [future.result(timeout=15) for future in [pool.submit(replay) for _ in range(5)]]
    assert sorted(response.status_code for response in responses) == [200, 200, 200, 200, 201]
    assert len({response.json()["run_id"] for response in responses}) == 1
    assert client.get("/api/runs").json()["total"] == 2
    with SessionLocal() as session:
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def test_unavailable_historical_model_rejects_rerun_without_creating_files_or_rows(queued_client):
    client = queued_client
    original = client.post("/api/runs", json=setup_run(client)).json()
    identity = str(uuid4())
    with SessionLocal() as session:
        source = session.get(Run, original["run_id"])
        values = {column.name: deepcopy(getattr(source, column.name)) for column in Run.__table__.columns}
        values.update(id=identity, model_version="unavailable-legacy-model", idempotency_key=None)
        values["input_snapshot"]["model_version"] = "unavailable-legacy-model"
        session.add(Run(**values))
        session.commit()
    before = set(RUNS_DIR.iterdir())
    response = client.post(f"/api/runs/{identity}/rerun")
    assert response.status_code == 409 and response.json()["code"] == "MODEL_VERSION_UNAVAILABLE"
    assert client.get("/api/runs").json()["total"] == 2
    assert set(RUNS_DIR.iterdir()) == before


@pytest.mark.parametrize("key", [" ", "x" * 201])
def test_rerun_key_and_missing_source_validation(queued_client, key):
    client = queued_client
    original = client.post("/api/runs", json=setup_run(client)).json()
    response = client.post(f"/api/runs/{original['run_id']}/rerun", headers={"Idempotency-Key": key})
    assert response.status_code == 400 and response.json()["code"] == "INVALID_IDEMPOTENCY_KEY"
    assert client.post("/api/runs/missing/rerun").json()["code"] == "RUN_NOT_FOUND"
    assert client.get("/api/runs").json()["total"] == 1


def test_fixed_rerun_reproduces_result_after_scene_deletion_without_mutating_source(client):
    body = setup_run(client)
    original = client.post("/api/runs", json=body).json()
    assert wait_terminal(client, original["run_id"])["status"] == "succeeded"
    before = client.get(f"/api/runs/{original['run_id']}/result").json()
    source_bytes = (RUNS_DIR / original["run_id"] / "result.json").read_bytes()
    assert client.delete(f"/api/scenes/{body['scene_id']}", headers={"If-Match": '"1"'}).status_code == 204
    response = client.post(f"/api/runs/{original['run_id']}/rerun", headers={"Idempotency-Key": "reproduce-success"})
    assert response.status_code == 201, response.text
    current = response.json()
    assert wait_terminal(client, current["run_id"])["status"] == "succeeded"
    after = client.get(f"/api/runs/{current['run_id']}/result").json()
    assert {key: value for key, value in before.items() if key not in {"run_id", "created_at"}} == {
        key: value for key, value in after.items() if key not in {"run_id", "created_at"}}
    assert current["inputs_sha256"] == original["inputs_sha256"]
    assert (RUNS_DIR / original["run_id"] / "result.json").read_bytes() == source_bytes

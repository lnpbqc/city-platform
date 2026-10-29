import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Run
from app.contracts import RunInputSnapshot
from app.run_artifacts import RUNS_DIR
from app.run_store import inputs_hash
from app.run_worker import RunQueue
from test_scenes import draft, layer_state, upload


@pytest.fixture
def paused_queue(monkeypatch):
    monkeypatch.setattr(RunQueue, "_loop", lambda self: self._stop.wait())


@pytest.fixture
def queued_client(paused_queue, client):
    return client


def setup_run(client, **changes):
    scene = client.post("/api/scenes", json=draft()).json()
    return {"scene_id": scene["id"], "network": {"asset_id": "net-001", "version": "1.0.0"},
            "origin": "S", "destination": "T", "blocked_edges": ["B-T"], **changes}


def wait_terminal(client, identity, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = client.get(f"/api/runs/{identity}").json()
        if record["status"] in {"succeeded", "failed", "cancelled"}:
            return record
        time.sleep(0.03)
    raise AssertionError(f"Run {identity} did not finish")


def test_persisted_input_idempotency_and_canonical_hash(queued_client):
    client = queued_client
    body = setup_run(client)
    first = client.post("/api/runs", json=body, headers={"Idempotency-Key": "same"})
    assert first.status_code == 201
    run = first.json()
    assert run["status"] == "queued" and run["started_at"] is None and run["finished_at"] is None
    assert run["trace_id"] == first.headers["x-trace-id"]
    again = client.post("/api/runs", json={**body, "blocked_edges": ["B-T", "B-T"], "seed": 0, "params": {"mode": "car"}}, headers={"Idempotency-Key": "same"})
    assert again.status_code == 200 and again.json() == run
    conflict = client.post("/api/runs", json={**body, "destination": "S"}, headers={"Idempotency-Key": "same"})
    assert conflict.status_code == 409 and conflict.json()["code"] == "IDEMPOTENCY_CONFLICT"
    another = client.post("/api/runs", json=body, headers={"Idempotency-Key": "new"}).json()
    assert another["run_id"] != run["run_id"] and another["inputs_sha256"] == run["inputs_sha256"]
    snapshot = client.get(f"/api/runs/{run['run_id']}/input").json()
    scene = {key: value for key, value in snapshot["scene"].items() if key not in {"id", "version", "created_at", "updated_at", "run_id"}}
    scene["layers"] = sorted(scene["layers"], key=lambda layer: (layer["order"], layer["layer_id"]))
    scene["blocked_edges"] = sorted(set(scene["blocked_edges"]))
    expected = {"request": snapshot["request"], "scene_version": run["scene_version"], "scene": scene,
                "model_version": run["model_version"], "data_version": run["data_version"]}
    canonical = json.dumps(expected, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(canonical).hexdigest() == run["inputs_sha256"]
    folder = RUNS_DIR / run["run_id"]
    assert json.loads((folder / "input.json").read_text(encoding="utf-8")) == snapshot
    assert run["trace_id"] in (folder / "run.log").read_text(encoding="utf-8")
    assert not (folder / "result.json").exists()


@pytest.mark.parametrize("change,code", [({"blocked_edges": ["T-B"]}, "INVALID_EDGE"),
    ({"origin": "bad"}, "INVALID_NODE"), ({"scene_id": "missing"}, "SCENE_NOT_FOUND"),
    ({"network": {"asset_id": "net-001", "version": "missing"}}, "NETWORK_NOT_FOUND")])
def test_invalid_run_input_creates_no_run_or_files(queued_client, change, code):
    body = setup_run(queued_client)
    before = sorted(path.name for path in RUNS_DIR.iterdir())
    response = queued_client.post("/api/runs", json={**body, **change})
    assert response.status_code in {404, 422} and response.json()["code"] == code
    assert queued_client.get("/api/runs").json()["total"] == 0
    assert sorted(path.name for path in RUNS_DIR.iterdir()) == before


def test_queue_cancel_and_terminal_cannot_return_to_queue(queued_client):
    client = queued_client
    run = client.post("/api/runs", json=setup_run(client)).json()
    identity = run["run_id"]
    assert client.get(f"/api/runs/{identity}/result").status_code == 409
    cancelled = client.post(f"/api/runs/{identity}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled" and cancelled.json()["finished_at"].endswith("Z")
    assert cancelled.json()["started_at"] is None
    assert client.post(f"/api/runs/{identity}/cancel").status_code == 409
    assert "cancelled" in client.get(f"/api/runs/{identity}/logs").text
    with SessionLocal() as session:
        with pytest.raises(IntegrityError):
            session.execute(update(Run).where(Run.id == identity).values(status="queued"))
        session.rollback()
        with pytest.raises(IntegrityError):
            session.execute(update(Run).where(Run.id == identity).values(inputs_sha256="0" * 64))
        session.rollback()


def test_run_list_filters_pagination_and_scene_version_hash(queued_client):
    client = queued_client
    body = setup_run(client)
    first = client.post("/api/runs", json=body).json()
    client.post(f"/api/runs/{first['run_id']}/cancel")
    assert client.put(f"/api/scenes/{body['scene_id']}", json={**draft(), "name": "version2"}, headers={"If-Match": '"1"'}).status_code == 200
    second = client.post("/api/runs", json=body).json()
    assert second["scene_version"] == 2 and second["inputs_sha256"] != first["inputs_sha256"]
    page = client.get("/api/runs?page_size=1").json()
    later = client.get("/api/runs?page_size=1&page=2").json()
    assert page["total"] == 2 and page["items"][0]["run_id"] != later["items"][0]["run_id"]
    assert client.get("/api/runs?status=cancelled").json()["total"] == 1
    assert client.get("/api/runs?scene_id=missing").json()["items"] == []
    assert client.get("/api/runs?from=2000-01-01T00:00:00Z&to=2099-01-01T00:00:00Z").json()["total"] == 2
    assert client.get("/api/runs?from=2099-01-01T00:00:00Z&to=2000-01-01T00:00:00Z").status_code == 422
    assert client.get("/api/runs?page=999999999999999999999").json()["items"] == []
    for query in ["page_size=101", "status=bad", "page=0"]:
        assert client.get("/api/runs?" + query).status_code == 422
    assert client.get("/api/runs/missing").json()["code"] == "RUN_NOT_FOUND"
    assert client.get("/api/stats/overview").json()["run_count"] == 2


def test_concurrent_same_key_has_one_run(queued_client):
    client = queued_client
    body = setup_run(client)
    barrier = Barrier(5)

    def submit():
        barrier.wait(timeout=5)
        return client.post("/api/runs", json=body, headers={"Idempotency-Key": "concurrent"})

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = [future.result(timeout=15) for future in [executor.submit(submit) for _ in range(5)]]
    assert sorted(response.status_code for response in results) == [200, 200, 200, 200, 201]
    assert len({response.json()["run_id"] for response in results}) == 1
    assert client.get("/api/runs").json()["total"] == 1


def test_worker_results_logs_download_and_immutable_storage(client):
    body = setup_run(client)
    created = client.post("/api/runs", json=body).json()
    identity = created["run_id"]
    record = wait_terminal(client, identity)
    assert record["status"] == "succeeded", record
    assert record["started_at"] and record["finished_at"] and record["elapsed_ms"] >= 0
    result = client.get(f"/api/runs/{identity}/result")
    assert result.status_code == 200
    data = result.json()
    assert data["run_id"] == identity
    assert data["baseline"]["length_m"] == 660 and data["blocked"]["length_m"] == 960
    assert data["baseline"]["duration_s"] == 66 and data["blocked"]["duration_s"] == 96
    assert data["metrics"]["increase_percent"] == pytest.approx(45.45454545454545)
    expected = (RUNS_DIR / identity / "result.json").read_bytes()
    download = client.get(f"/api/runs/{identity}/download?format=json")
    assert download.content == expected and download.json() == data
    exported = client.get(f"/api/runs/{identity}/download?format=geojson").json()
    assert exported["type"] == "FeatureCollection"
    assert {feature["properties"]["role"] for feature in exported["features"]} == {"baseline", "blocked", "blocked_edge"}
    log = client.get(f"/api/runs/{identity}/logs").text
    assert all(value in log for value in ["queued", "running", "succeeded", record["trace_id"]])
    assert client.post(f"/api/runs/{identity}/cancel").status_code == 409
    assert client.put(f"/api/runs/{identity}/result", json={}).status_code == 405
    with SessionLocal() as session:
        with pytest.raises(IntegrityError):
            session.execute(update(Run).where(Run.id == identity).values(result={"changed": True}))
        session.rollback()
    assert (RUNS_DIR / identity / "result.json").read_bytes() == expected


def test_five_jobs_do_not_mix_inputs_or_results(client):
    body = setup_run(client)
    cases = [([], "T", 660), (["B-T"], "T", 960), (["S-A"], "T", None), ([], "S", 0), (["A-C"], "T", 660)]
    runs = [(client.post("/api/runs", json={**body, "blocked_edges": edges, "destination": end, "seed": index}).json(), length)
            for index, (edges, end, length) in enumerate(cases)]
    assert len({run["run_id"] for run, _ in runs}) == 5
    for run, length in runs:
        assert wait_terminal(client, run["run_id"])["status"] == "succeeded"
        result = client.get(f"/api/runs/{run['run_id']}/result").json()
        assert result["run_id"] == run["run_id"] and result["blocked"]["length_m"] == length


def test_history_references_survive_scene_delete_and_scene_can_reference_run(queued_client):
    client = queued_client
    layer = upload(client).json()
    scene_body = {**draft(), "layers": [layer_state(layer)]}
    scene = client.post("/api/scenes", json=scene_body).json()
    body = {**setup_run(client), "scene_id": scene["id"]}
    run = client.post("/api/runs", json=body).json()
    updated = client.put(f"/api/scenes/{scene['id']}", json={**scene_body, "run_id": run["run_id"]}, headers={"If-Match": '"1"'})
    assert updated.status_code == 200
    assert client.delete(f"/api/scenes/{scene['id']}", headers={"If-Match": '"2"'}).status_code == 204
    client.delete(f"/api/layers/{layer['id']}")
    asset = client.get(f"/api/assets/{layer['asset_id']}").json()
    assert asset["references"] == [{"type": "run", "id": run["run_id"], "name": draft()["name"], "version": 1, "asset_version": "1.0.0"}]
    assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 409
    assert client.get(f"/api/runs/{run['run_id']}/input").json()["scene"]["layers"] == scene_body["layers"]


def test_missing_artifacts_rebuild_but_changed_input_is_reported(queued_client):
    client = queued_client
    run = client.post("/api/runs", json=setup_run(client)).json()
    path = RUNS_DIR / run["run_id"] / "input.json"
    original = path.read_bytes()
    path.unlink()
    response = client.post("/api/runs/reconcile")
    assert response.status_code == 200 and path.read_bytes() == original
    path.write_text("{}", encoding="utf-8")
    response = client.get(f"/api/runs/{run['run_id']}/input")
    assert response.status_code == 409 and response.json()["code"] == "RUN_ARTIFACT_CHANGED"
    assert path.read_text(encoding="utf-8") == "{}"
    report = client.post("/api/runs/reconcile").json()
    assert any(issue["run_id"] == run["run_id"] for issue in report["issues"])


def test_hash_uses_versions_and_input_state_but_not_run_display_or_metadata(queued_client):
    client = queued_client
    run = client.post("/api/runs", json=setup_run(client)).json()
    snapshot = client.get(f"/api/runs/{run['run_id']}/input").json()
    altered = deepcopy(snapshot)
    altered["scene"].update(run_id="another-run", created_at="2000-01-01T00:00:00Z", updated_at="2099-01-01T00:00:00Z")
    altered["request"]["blocked_edges"] *= 2
    assert inputs_hash(RunInputSnapshot.model_validate(altered)) == run["inputs_sha256"]
    for mutate in [lambda value: value["scene"].update(version=2),
                   lambda value: value.update(model_version="next-model"),
                   lambda value: value.update(data_version="net-001@2"),
                   lambda value: value["request"].update(seed=99),
                   lambda value: value["scene"]["camera"].update(height=900)]:
        altered = deepcopy(snapshot)
        mutate(altered)
        assert inputs_hash(RunInputSnapshot.model_validate(altered)) != run["inputs_sha256"]


@pytest.mark.parametrize("target", ["folder", "input"])
def test_run_artifact_links_cannot_touch_outside_files(queued_client, tmp_path, monkeypatch, target):
    import os
    import shutil
    import subprocess

    client = queued_client
    run = client.post("/api/runs", json=setup_run(client)).json()
    folder = RUNS_DIR / run["run_id"]
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "input.json"
    marker.write_text("keep", encoding="utf-8")
    if target == "folder":
        assert folder.resolve().is_relative_to(RUNS_DIR.resolve())
        shutil.rmtree(folder)
        link = folder
        if os.name == "nt":
            created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
            assert created.returncode == 0
        else:
            link.symlink_to(outside, target_is_directory=True)
    else:
        link = folder / "input.json"
        link.unlink()
        try:
            link.symlink_to(marker)
        except OSError:
            # Without Windows symlink privileges, inject the filesystem's
            # reparse attribute and verify rejection before any file access.
            import stat
            from pathlib import Path
            from types import SimpleNamespace
            link.write_text("reparse-placeholder", encoding="utf-8")
            original_lstat = Path.lstat
            monkeypatch.setattr(Path, "lstat", lambda path: SimpleNamespace(st_mode=stat.S_IFREG,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT) if path == link else original_lstat(path))
    try:
        response = client.get(f"/api/runs/{run['run_id']}/input")
        assert response.status_code == 409 and response.json()["code"] == "RUN_ARTIFACT_UNSAFE"
        assert marker.read_text(encoding="utf-8") == "keep"
    finally:
        if link.is_junction():
            os.rmdir(link)
        else:
            link.unlink()


def test_success_artifacts_rebuild_without_overwriting_changed_result(client):
    run = client.post("/api/runs", json=setup_run(client)).json()
    assert wait_terminal(client, run["run_id"])["status"] == "succeeded"
    assert client.get(f"/api/runs/{run['run_id']}/result").status_code == 200
    path = RUNS_DIR / run["run_id"] / "result.json"
    original = path.read_bytes()
    path.unlink()
    response = client.get(f"/api/runs/{run['run_id']}/download")
    assert response.status_code == 200 and response.content == original and path.read_bytes() == original
    path.write_text("{}", encoding="utf-8")
    assert client.get(f"/api/runs/{run['run_id']}/result").json()["code"] == "RUN_ARTIFACT_CHANGED"
    assert client.get(f"/api/runs/{run['run_id']}").json()["status"] == "succeeded"
    assert path.read_text(encoding="utf-8") == "{}"


def test_failed_database_commit_does_not_publish_success_result(queued_client, monkeypatch):
    from sqlalchemy.orm import Session
    from app.run_store import claim_next, finish_run, recover_runs

    run = queued_client.post("/api/runs", json=setup_run(queued_client)).json()
    identity = run["run_id"]
    assert claim_next() == identity
    original_commit = Session.commit

    def reject_success(session):
        if any(isinstance(record, Run) and record.status == "succeeded" for record in session.identity_map.values()):
            raise RuntimeError("commit interrupted")
        return original_commit(session)

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", reject_success)
        with pytest.raises(RuntimeError, match="commit interrupted"):
            finish_run(identity, "succeeded", result={"run_id": identity})
    assert not (RUNS_DIR / identity / "result.json").exists()
    assert queued_client.get(f"/api/runs/{identity}").json()["status"] == "running"
    recover_runs()
    assert queued_client.get(f"/api/runs/{identity}").json()["error"]["code"] == "RUN_INTERRUPTED"
    assert queued_client.post("/api/runs/reconcile").json()["issues"] == []


def test_uncommitted_result_file_is_reported_and_preserved(queued_client):
    run = queued_client.post("/api/runs", json=setup_run(queued_client)).json()
    path = RUNS_DIR / run["run_id"] / "result.json"
    path.write_bytes(b'{"uncommitted":true}')
    report = queued_client.post("/api/runs/reconcile").json()
    assert any(issue["run_id"] == run["run_id"] and issue["code"] == "ORPHAN_RUN_RESULT" for issue in report["issues"])
    assert path.read_bytes() == b'{"uncommitted":true}'

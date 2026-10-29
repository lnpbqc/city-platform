import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.main import app
from app.models import Asset
from test_runs import paused_queue, queued_client  # noqa: F401


@pytest.mark.parametrize("legacy", [True, False])
def test_overview_reads_one_snapshot_during_asset_deletion(queued_client, monkeypatch, legacy):
    data = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [value, value]}}
        for value in (0.25, 0.75)
    ]}
    response = queued_client.post("/api/layers/upload", data={"name": "统计快照", "type": "geojson"},
                                  files={"file": ("points.geojson", json.dumps(data).encode(), "application/json")})
    assert response.status_code == 201, response.text
    layer = response.json()
    identity = layer["asset_id"]
    assert queued_client.delete(f"/api/layers/{layer['id']}").status_code == 204
    baseline = queued_client.get("/api/stats/overview").json()
    assert baseline["asset_count"] == 1 and baseline["object_count"] == 2
    assert baseline["total_byte_size"] > 0

    selected, release_reader, writer_committing, writer_finished = Event(), Event(), Event(), Event()
    observed = {}
    execute = Session.execute

    def paused_counts(session, statement, *args, **kwargs):
        sql = str(statement)
        if legacy and sql == "BEGIN":
            return None
        result = execute(session, statement, *args, **kwargs)
        if "GROUP BY assets.type" in sql and not selected.is_set():
            # Consume the cursor before pausing: only an explicit transaction
            # may keep the subsequent aggregate queries on the same snapshot.
            frozen = result.freeze()
            observed["read_transaction"] = session.connection().connection.driver_connection.in_transaction
            selected.set()
            assert release_reader.wait(10), "主线程应在独立删除开始后恢复统计读取"
            return frozen()
        return result

    def before_commit(session):
        if any(isinstance(value, Asset) and value.id == identity and value.status == "deleting" for value in session.dirty):
            writer_committing.set()

    monkeypatch.setattr(Session, "execute", paused_counts)
    event.listen(Session, "before_commit", before_commit)
    http = TestClient(app, raise_server_exceptions=False)

    def delete():
        try:
            return http.delete(f"/api/assets/{identity}")
        finally:
            writer_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            reading = executor.submit(http.get, "/api/stats/overview")
            try:
                assert selected.wait(10)
                deleting = executor.submit(delete)
                assert writer_committing.wait(10)
                if legacy:
                    assert not observed["read_transaction"]
                    assert writer_finished.wait(10)
                else:
                    assert observed["read_transaction"]
                    assert not writer_finished.wait(0.05)
            finally:
                release_reader.set()
            result = reading.result(timeout=10)
            deletion = deleting.result(timeout=10)
        assert result.status_code == 200, result.text
        assert deletion.status_code == 204, deletion.text
        body = result.json()
        if legacy:
            assert body["asset_count"] == 1
            assert body["total_byte_size"] == body["object_count"] == body["assets_added_last_7_days"] == 0
        else:
            assert body == baseline
        assert http.get("/api/stats/overview").json()["asset_count"] == 0
    finally:
        release_reader.set()
        event.remove(Session, "before_commit", before_commit)
        http.close()

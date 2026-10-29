import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import object_queries
from app.main import app
from app.models import Asset


@pytest.mark.parametrize("operation", ["list", "select", "summary"])
def test_object_read_snapshot_survives_concurrent_asset_deletion(client, monkeypatch, operation):
    data = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [value, value]}}
        for value in (0.25, 0.75)
    ]}
    response = client.post("/api/layers/upload", data={"name": "并发快照", "type": "geojson"},
                           files={"file": ("points.geojson", json.dumps(data).encode(), "application/json")})
    assert response.status_code == 201, response.text
    layer = response.json()
    identity = layer["asset_id"]
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204

    selected, release_reader, writer_committing, writer_finished = Event(), Event(), Event(), Event()
    observed = {}
    select_objects = object_queries.select_objects

    def paused_selection(session, query, polygon=None):
        result = select_objects(session, query, polygon)
        if query.asset_id == identity:
            observed["read_transaction"] = session.connection().connection.driver_connection.in_transaction
            selected.set()
            assert release_reader.wait(10), "主线程应在写请求开始后恢复读取"
        return result

    def before_commit(session):
        if any(isinstance(value, Asset) and value.id == identity and value.status == "deleting" for value in session.dirty):
            writer_committing.set()

    monkeypatch.setattr(object_queries, "select_objects", paused_selection)
    event.listen(Session, "before_commit", before_commit)
    http = TestClient(app, raise_server_exceptions=False)

    def read():
        if operation == "select":
            return http.post("/api/objects/select", json={"asset_id": identity, "geometry": {
                "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            }})
        path = "/api/objects/summary" if operation == "summary" else "/api/objects"
        return http.get(path, params={"asset_id": identity, "bbox": "0,0,1,1"})

    def delete():
        try:
            return http.delete(f"/api/assets/{identity}")
        finally:
            writer_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            reading = executor.submit(read)
            try:
                assert selected.wait(10), "读取请求应先选中对象"
                deleting = executor.submit(delete)
                assert writer_committing.wait(10), "独立删除请求应开始提交"
                if observed["read_transaction"]:
                    # A real read snapshot blocks the writer's commit until the
                    # reader completes. Never wait for that commit in the reader.
                    assert not writer_finished.wait(0.05)
                else:
                    # Also makes the legacy no-BEGIN reproduction deterministic:
                    # without a read transaction, the writer can finish now.
                    assert writer_finished.wait(10)
            finally:
                release_reader.set()
            result = reading.result(timeout=10)
            deletion = deleting.result(timeout=10)
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["total"] == 2
        if operation == "summary":
            assert sum(group["count"] for group in body["types"]) == body["total"]
        else:
            assert len(body["items"]) == body["total"]
            assert len({item["object_id"] for item in body["items"]}) == 2
        assert deletion.status_code == 204, deletion.text
        assert http.get(f"/api/assets/{identity}").status_code == 404
    finally:
        release_reader.set()
        event.remove(Session, "before_commit", before_commit)
        http.close()

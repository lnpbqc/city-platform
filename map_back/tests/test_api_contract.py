import logging

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app


def test_service_version_and_health_have_trace_headers(client):
    health = client.get("/api/health")
    version = client.get("/api/version")
    assert health.json() == {"status": "ok"}
    assert version.status_code == 200
    assert version.json() == {"service_version": "0.2.0", "api_version": "1.0",
                              "model_version": "dijkstra-undirected-v1", "data_version": "net-001@1.0.0"}
    assert len(health.headers["X-Trace-ID"]) == 32
    assert version.headers["X-Trace-ID"] != health.headers["X-Trace-ID"]


def test_missing_asset_preserves_legacy_detail_and_adds_error_envelope(client):
    response = client.get("/api/assets/missing")
    body = response.json()
    assert response.status_code == 404
    assert body["code"] == "ASSET_NOT_FOUND"
    assert body["message"] == body["detail"] == "文件资产不存在"
    assert body["trace_id"] == response.headers["X-Trace-ID"]


def test_request_validation_is_json_serializable_and_preserves_legacy_errors(client):
    response = client.post("/api/layers", json={"name": "bad", "type": "geojson", "url": "D:/private.json"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert isinstance(body["detail"], list)
    assert "磁盘路径" in body["message"]
    assert body["trace_id"] == response.headers["X-Trace-ID"]


@pytest.mark.parametrize(("status", "detail", "code"), [
    (400, "请求参数无效", "INVALID_ARGUMENT"),
    (409, {"message": "资产仍被引用", "references": [{"id": "one", "name": "图层"}]}, "ASSET_IN_USE"),
    (413, "ZIP 解压总量超过 2048 MiB", "PAYLOAD_TOO_LARGE"),
    (422, "ZIP 包含不安全路径", "CONTENT_INVALID"),
])
def test_domain_errors_keep_status_and_legacy_detail(client, status, detail, code):
    def fail():
        raise HTTPException(status, detail)

    app.dependency_overrides[get_session] = fail
    try:
        response = client.get("/api/layers")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["detail"] == detail
    assert body["trace_id"] == response.headers["X-Trace-ID"]


def test_unexpected_error_is_logged_with_trace_without_leaking_details(client, caplog):
    def fail():
        raise RuntimeError("private filesystem detail")

    app.dependency_overrides[get_session] = fail
    try:
        with caplog.at_level(logging.ERROR), TestClient(app, raise_server_exceptions=False) as isolated:
            response = isolated.get("/api/layers")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR"
    assert body["trace_id"] == response.headers["X-Trace-ID"]
    assert "private filesystem detail" not in response.text
    assert body["trace_id"] in caplog.text
    assert "private filesystem detail" in caplog.text


def test_cors_accepts_version_and_idempotency_headers_and_exposes_trace(client):
    response = client.options("/api/layers/example", headers={
        "Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "If-Match,Idempotency-Key,Content-Type",
    })
    assert response.status_code == 200
    actual = client.get("/api/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert "x-trace-id" in actual.headers["Access-Control-Expose-Headers"].lower()


def test_openapi_describes_shared_error_and_version_contracts(client):
    specification = client.get("/openapi.json").json()
    version = specification["paths"]["/api/version"]["get"]
    assert version["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("VersionOutput")
    for status in ("400", "404", "409", "413", "422", "500"):
        schema = specification["paths"]["/api/layers"]["post"]["responses"][status]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("ErrorEnvelope")

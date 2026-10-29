import json
from datetime import datetime, timedelta, timezone

import pytest

from app import assets
from app.database import FILES_DIR, SessionLocal
from app.models import Asset
from test_layers import GEO, upload


def seed_assets():
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        for identity, kind, size, age, status, source_kind in [
            ("a", "geojson", 20, 1, "active", "upload"),
            ("b", "3dtiles", 20, 2, "active", "default"),
            ("c", "unknown", 0, 9, "missing", "upload"),
            ("d", "3dtiles", 0, 0, "active", "external"),
        ]:
            session.add(Asset(id=identity, name="校区_100%" if identity == "a" else "模型" + identity,
                              original_name=identity + ".zip", type=kind, byte_size=size, file_count=1,
                              source="测绘" if identity == "b" else "", source_kind=source_kind,
                              discovered_at=now - timedelta(days=age), status=status))
        session.commit()
    return now


def test_explicit_pagination_returns_stable_pages_without_duplicates(client):
    seed_assets()
    first = client.get("/api/assets", params={"page": 1, "page_size": 2}).json()
    second = client.get("/api/assets", params={"page": 2, "page_size": 2}).json()
    assert isinstance(first, dict), first
    assert first["total"] == second["total"] == 4
    assert first["page"] == 1 and first["page_size"] == 2
    assert [x["id"] for x in first["items"] + second["items"]] == ["d", "a", "b", "c"]
    assert client.get("/api/assets?page=3&page_size=2").json()["items"] == []
    assert client.get("/api/assets?page_size=1").json()["page"] == 1
    assert client.get("/api/assets?page=1").json()["page_size"] == 20
    assert isinstance(client.get("/api/assets").json(), list)


def test_catalog_filters_combine_and_keyword_search_is_literal(client):
    now = seed_assets()
    response = client.get("/api/assets", params={"page": 1, "type": "3dtiles", "status": "ready", "q": "测绘",
                          "from": (now - timedelta(days=3)).isoformat(), "to": now.isoformat()})
    assert response.status_code == 200, response.text
    assert [x["id"] for x in response.json()["items"]] == ["b"]
    assert [x["id"] for x in client.get("/api/assets?page=1&status=missing").json()["items"]] == ["c"]
    assert client.get("/api/assets", params={"page": 1, "q": "100%"}).json()["total"] == 1
    assert client.get("/api/assets", params={"page": 1, "q": "_"}).json()["total"] == 1
    assert client.get("/api/assets", params={"page": 1, "q": "not-found"}).json()["total"] == 0
    assert isinstance(client.get("/api/assets?type=geojson").json(), list)


def test_volume_sort_is_stable_with_unknown_external_size_last(client):
    seed_assets()
    ascending = client.get("/api/assets?page=1&sort=byte_size").json()
    descending = client.get("/api/assets?page=1&sort=-byte_size").json()
    assert isinstance(ascending, dict), ascending
    assert [x["id"] for x in ascending["items"]] == ["c", "a", "b", "d"]
    assert [x["id"] for x in descending["items"]] == ["a", "b", "c", "d"]
    assert descending["items"][-1]["byte_size"] is None


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101", "type=invalid", "status=invalid",
                                   "sort=name", "from=not-a-date", "from=2026-10-25T00:00:00",
                                   "from=2026-10-26T00:00:00Z&to=2026-10-25T00:00:00Z"])
def test_query_validation_has_unified_error(client, query):
    response = client.get("/api/assets?" + query)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["trace_id"] == response.headers["X-Trace-ID"]


def test_stats_count_catalogued_assets_local_capacity_and_last_seven_days(client):
    seed_assets()
    response = client.get("/api/stats/overview")
    assert response.status_code == 200, response.text
    assert response.json() == {"asset_count": 4, "object_count": 0, "run_count": 0, "total_byte_size": 40,
                              "assets_by_type": {"geojson": 1, "3dtiles": 2, "unknown": 1}, "assets_added_last_7_days": 3}


def test_empty_catalog_stats_and_page(client):
    response = client.get("/api/stats/overview")
    assert response.status_code == 200, response.text
    assert response.json() == {"asset_count": 0, "object_count": 0, "run_count": 0, "total_byte_size": 0,
                              "assets_by_type": {}, "assets_added_last_7_days": 0}
    assert client.get("/api/assets?page=1").json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_huge_out_of_range_page_returns_empty_without_sqlite_integer_overflow(client):
    seed_assets()
    response = client.get("/api/assets?page=9223372036854775808&page_size=100")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 4 and response.json()["items"] == []


def test_pages_and_stats_use_catalog_without_scanning_files(client, monkeypatch):
    layer = upload(client, json.dumps(GEO).encode()).json()
    def forbidden(*args, **kwargs):
        raise AssertionError("分页和统计不得扫描文件")
    monkeypatch.setattr(assets, "inventory", forbidden)
    monkeypatch.setattr(assets, "build_metadata", forbidden)
    response = client.get("/api/assets?page=1")
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["id"] == layer["asset_id"]
    assert client.get("/api/stats/overview").status_code == 200


def test_missing_directory_reconciles_current_capacity_but_keeps_version_fingerprint(client):
    layer = upload(client, json.dumps(GEO).encode()).json()
    identity = layer["asset_id"]
    original = client.get(f"/api/assets/{identity}/versions/1.0.0").json()
    folder = FILES_DIR / identity
    (folder / "data.geojson").unlink()
    folder.rmdir()
    assert client.post("/api/assets/reconcile").status_code == 200
    record = client.get("/api/assets?page=1&status=missing").json()["items"][0]
    assert record["byte_size"] == record["file_count"] == 0
    assert client.get("/api/stats/overview").json()["total_byte_size"] == 0
    assert client.get(f"/api/assets/{identity}/versions/1.0.0").json()["sha256"] == original["sha256"]
    assert client.get(f"/api/assets/{identity}/versions/1.0.0").json()["byte_size"] == original["byte_size"]


def test_time_filter_uses_uploaded_time_utc_and_inclusive_endpoints(client):
    seed_assets()
    instant = datetime(2026, 10, 25, 4, tzinfo=timezone.utc)
    with SessionLocal() as session:
        session.get(Asset, "a").uploaded_at = instant
        session.commit()
    response = client.get("/api/assets", params={"page": 1, "from": "2026-10-25T12:00:00+08:00", "to": instant.isoformat()})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == ["a"]

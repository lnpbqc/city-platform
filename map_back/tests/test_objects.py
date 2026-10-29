import json

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import shape

from app.database import FILES_DIR, SessionLocal
from app.main import app
from app.models import Asset, AssetVersion, SpatialObject
from test_layers import TILESET, upload, zip_data


def features():
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "duplicate", "properties": {"name": "点A", "object_type": "point", "confidence": 0}, "geometry": {"type": "Point", "coordinates": [0.5, 0.5]}},
        {"type": "Feature", "id": "duplicate", "properties": {"name": "道路", "object_type": "road", "level": "主干道"}, "geometry": {"type": "LineString", "coordinates": [[-2, 0.5], [2, 0.5]]}},
        {"type": "Feature", "properties": {"name": "建筑", "object_type": "building", "height_m": 12, "semantic_source": "manual", "confidence": 0.8}, "geometry": {"type": "Polygon", "coordinates": [[[-1, -1], [2, -1], [2, 2], [-1, 2], [-1, -1]]]}},
        {"type": "Feature", "properties": {}, "geometry": None},
    ]}


def uploaded(client, data=None):
    layer = upload(client, json.dumps(data or features()).encode()).json()
    assert "asset_id" in layer, layer
    return layer


def query(client, layer, **params):
    response = client.get("/api/objects", params={"asset_id": layer["asset_id"], **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_objects_have_stable_unique_ids_pagination_details_and_real_properties(client):
    layer = uploaded(client)
    rows = query(client, layer)["items"]
    assert len(rows) == 4 and len({row["object_id"] for row in rows}) == 4
    pages = [query(client, layer, page=page, page_size=1)["items"][0] for page in range(1, 5)]
    assert [row["object_id"] for row in pages] == [row["object_id"] for row in rows]
    assert query(client, layer, page=9223372036854775808)["items"] == []
    for row in rows:
        assert row["asset"] == {"asset_id": layer["asset_id"], "version": "1.0.0"}
        assert row["layer_id"] == layer["id"]
        assert client.get(f"/api/objects/{row['object_id']}").json() == row
    building = next(row for row in rows if row["type"] == "building")
    assert building["height_m"] == 12 and building["confidence"] == 0.8 and building["semantic_source"] == "manual"
    point = next(row for row in rows if row["type"] == "point")
    assert point["confidence"] == 0 and point["height_m"] is None
    assert client.get("/api/objects/absent").status_code == 404
    with TestClient(app) as restarted:
        assert [row["object_id"] for row in query(restarted, layer)["items"]] == [row["object_id"] for row in rows]


def test_bbox_really_clips_lines_and_polygons_and_summary_matches(client):
    layer = uploaded(client)
    page = query(client, layer, bbox="0,0,1,1")
    assert page["total"] == 3
    rows = page["items"]
    road = next(row for row in rows if row["type"] == "road")
    assert road["geometry"]["coordinates"] == [[0, 0.5], [1, 0.5]]
    building = next(row for row in rows if row["type"] == "building")
    assert shape(building["geometry"]).bounds == (0, 0, 1, 1)
    assert shape(client.get(f"/api/objects/{building['object_id']}").json()["geometry"]).bounds == (-1, -1, 2, 2)
    summary = client.get("/api/objects/summary", params={"asset_id": layer["asset_id"], "bbox": "0,0,1,1"}).json()
    assert summary["total"] == len(rows)
    groups = {row["type"]: row for row in summary["types"]}
    assert groups["road"]["area_m2"] is None
    assert 12_000_000_000 < groups["building"]["area_m2"] < 13_000_000_000
    assert groups["building"]["min_height_m"] == groups["building"]["max_height_m"] == 12


def test_spatial_selection_excludes_bbox_false_positives_and_counts_exact_set(client):
    data = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]],
    ]}}]}
    layer = uploaded(client, data)
    assert query(client, layer, bbox="1.5,1.5,2.5,2.5")["total"] == 0
    polygon = {"type": "Polygon", "coordinates": [[[1.5, 1.5], [2.5, 1.5], [2.5, 2.5], [1.5, 2.5], [1.5, 1.5]]]}
    response = client.post("/api/objects/select", json={"asset_id": layer["asset_id"], "geometry": polygon})
    assert response.status_code == 200 and response.json()["total"] == 0
    polygon["coordinates"] = [[[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5], [-0.5, -0.5]]]
    response = client.post("/api/objects/select", json={"asset_id": layer["asset_id"], "geometry": polygon})
    assert response.json()["total"] == 1
    assert shape(response.json()["items"][0]["geometry"]).bounds == (0, 0, 0.5, 0.5)


def test_type_keyword_layer_and_version_filters_share_one_selection(client):
    layer = uploaded(client)
    assert query(client, layer, type="road", q="道路")["total"] == 1
    assert query(client, layer, q="not-found")["total"] == 0
    response = client.get("/api/objects", params={"layer_id": layer["id"], "version": "1.0.0"})
    assert response.status_code == 200 and response.json()["total"] == 4
    assert client.get("/api/objects?asset_id=absent").status_code == 404
    assert client.get("/api/objects?layer_id=absent").status_code == 404
    assert client.get("/api/objects", params={"asset_id": layer["asset_id"], "version": "absent"}).status_code == 404


@pytest.mark.parametrize("params", [{"bbox": "bad"}, {"bbox": "0,2,1,1"}, {"bbox": "nan,0,1,1"}, {"page": 0}, {"page_size": 101}, {"time": "2026-10-25T00:00:00"}])
def test_object_query_validation_has_trace_and_never_500(client, params):
    response = client.get("/api/objects", params=params)
    assert response.status_code == 422, response.text
    assert response.json()["trace_id"]


def test_model_without_semantics_is_not_fabricated_as_buildings(client):
    layer = upload(client, zip_data({"tileset.json": json.dumps(TILESET), "model.glb": b"geometry"}), "3dtiles", "model.zip").json()
    page = query(client, layer)
    assert page["total"] == 1
    row = page["items"][0]
    assert row["type"] == "model" and row["semantic_source"] == "geometry_model"
    assert row["geometry"] is None and row["properties"] == {}
    assert row["height_m"] is None and row["confidence"] is None
    assert query(client, layer, bbox="-180,-90,180,90")["total"] == 0


def test_layer_counts_and_overview_match_index_and_asset_delete_cascades(client):
    layer = uploaded(client)
    row = next(row for row in client.get("/api/layers/catalog").json() if row["id"] == layer["id"])
    before = client.get("/api/stats/overview").json()["object_count"]
    assert row["object_count"] == query(client, layer)["total"] == 4
    client.delete(f"/api/layers/{layer['id']}")
    orphan = query(client, layer)
    assert all(row["layer_id"] is None for row in orphan["items"])
    assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 204
    with SessionLocal() as session:
        assert session.query(SpatialObject).filter_by(asset_id=layer["asset_id"]).count() == 0
    assert client.get("/api/stats/overview").json()["object_count"] == before - 4


def test_multiple_layer_references_do_not_duplicate_features_and_keep_context(client):
    layer = uploaded(client)
    second = client.post("/api/layers", json={"name": "第二份登记", "type": "geojson", "url": layer["url"]}).json()
    page = client.get("/api/objects", params={"layer_id": second["id"]}).json()
    assert page["total"] == 4 and all(row["layer_id"] == second["id"] for row in page["items"])
    assert client.get("/api/stats/overview").json()["object_count"] == 4
    assert query(client, layer)["total"] == 4


def test_asset_default_version_and_pinned_layer_version_have_distinct_stable_ids(client):
    layer = uploaded(client)
    original = query(client, layer)["items"]
    with SessionLocal() as session:
        old = session.get(AssetVersion, (layer["asset_id"], "1.0.0"))
        session.add(AssetVersion(asset_id=old.asset_id, version="2.0.0", entry_url=old.entry_url,
                                 byte_size=old.byte_size, file_count=old.file_count, sha256=old.sha256,
                                 file_manifest=old.file_manifest, bounds=old.bounds))
        session.get(Asset, old.asset_id).current_version = "2.0.0"
        session.commit()
    assert client.post("/api/assets/reconcile").status_code == 200
    current = query(client, layer)["items"]
    assert all(row["asset"]["version"] == "2.0.0" for row in current)
    assert {row["object_id"] for row in original}.isdisjoint(row["object_id"] for row in current)
    pinned = client.get("/api/objects", params={"layer_id": layer["id"]}).json()["items"]
    assert [row["object_id"] for row in pinned] == [row["object_id"] for row in original]
    assert query(client, layer, version="1.0.0")["items"] == original
    assert client.get("/api/objects", params={"layer_id": layer["id"], "version": "2.0.0"}).status_code == 422
    assert client.get("/api/stats/overview").json()["object_count"] == 4


def test_unread_external_asset_has_unknown_count_and_explicit_index_error(client):
    external = client.post("/api/assets/register", json={"name": "外部点位", "type": "geojson", "location": "https://example.invalid/external.json"}).json()
    response = client.get("/api/objects", params={"asset_id": external["asset_id"]})
    assert response.status_code == 409 and response.json()["code"] == "OBJECT_INDEX_UNAVAILABLE"
    assert "外部" in response.json()["message"]


@pytest.mark.parametrize("geometry", [17, "invalid"])
def test_legacy_malformed_geometry_does_not_break_startup_or_reconcile(client, geometry):
    from uuid import uuid4
    identity = str(uuid4())
    folder = FILES_DIR / identity
    folder.mkdir()
    (folder / "data.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": geometry}]}), encoding="utf-8")
    response = client.post("/api/assets/reconcile")
    assert response.status_code == 200, response.text
    response = client.get("/api/objects", params={"asset_id": identity})
    assert response.status_code == 409 and response.json()["code"] == "OBJECT_INDEX_UNAVAILABLE"


def test_new_upload_rejects_self_intersection_and_nonfinite_properties(client):
    data = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]]}}]}
    response = upload(client, json.dumps(data).encode())
    assert response.status_code == 422 and response.json()["trace_id"]
    data = features()
    data["features"][0]["properties"]["value"] = float("nan")
    response = upload(client, json.dumps(data).encode())
    assert response.status_code == 422 and response.json()["trace_id"]
    assert client.get("/api/assets").json() == []


def test_legacy_crs_declaration_never_becomes_a_false_wgs84_index(client):
    from uuid import uuid4
    identity = str(uuid4())
    folder = FILES_DIR / identity
    folder.mkdir()
    data = {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:3857"}}, "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [1, 1]}}]}
    (folder / "data.geojson").write_text(json.dumps(data), encoding="utf-8")
    assert client.post("/api/assets/reconcile").status_code == 200
    response = client.get("/api/objects", params={"asset_id": identity})
    assert response.status_code == 409 and response.json()["code"] == "OBJECT_INDEX_UNAVAILABLE"
    assert "WGS84" in response.json()["message"]


def test_unavailable_asset_keeps_snapshot_but_catalog_count_becomes_unknown(client):
    layer = uploaded(client)
    original = query(client, layer)["items"]
    client.get("/api/layers/catalog")
    total = client.get("/api/stats/overview").json()["object_count"]
    with SessionLocal() as session:
        session.get(Asset, layer["asset_id"]).status = "unsafe"
        session.commit()
    assert client.get("/api/objects", params={"asset_id": layer["asset_id"]}).status_code == 409
    row = next(row for row in client.get("/api/layers/catalog").json() if row["id"] == layer["id"])
    assert row["object_count"] is None
    assert client.get("/api/stats/overview").json()["object_count"] == total - 4
    with SessionLocal() as session:
        assert session.query(SpatialObject).filter_by(asset_id=layer["asset_id"]).count() == 4
        assert session.get(SpatialObject, original[0]["object_id"]).properties == original[0]["properties"]

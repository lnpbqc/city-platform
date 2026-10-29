from fastapi.testclient import TestClient
import pytest

from app.main import app
from test_layers import GEO, upload
import json
from uuid import uuid4

from app.database import FILES_DIR, SessionLocal
from app.models import Layer


def catalog(client, campus="university-town"):
    response = client.get("/api/layers/catalog", params={"campus": campus})
    assert response.status_code == 200, response.text
    return response.json()


def test_catalog_exposes_grouped_defaults_pinned_versions_legends_and_depth_rules(client):
    rows = catalog(client)
    by_id = {row["id"]: row for row in rows}
    assert len(rows) == 6
    assert by_id["basemap"]["category"] == "底图"
    assert by_id["campus-buildings"]["category"] == "建筑"
    assert by_id["demo-roads"]["category"] == "道路"
    assert by_id["demo-points"]["category"] == "专题"
    assert by_id["demo-points"]["unit"] == by_id["demo-areas"]["unit"] == "cm"
    assert by_id["demo-roads"]["unit"] == "辆/小时"
    assert not by_id["campus-buildings"]["orderable"] and not by_id["demo-buildings"]["orderable"]
    assert by_id["demo-roads"]["orderable"]
    assert all(row["static"] and isinstance(row["object_count"], int) for row in rows)
    assert by_id["basemap"]["object_count"] == 0 and by_id["demo-buildings"]["object_count"] == 1
    for row in rows:
        assert row["builtin"] and row["legend"]
        if row["id"] != "basemap":
            asset = client.get(f"/api/assets/{row['asset']['asset_id']}").json()
            assert asset["protected"] and asset["source_kind"] == "default"
            assert row["asset"]["version"] == asset["current_version"] == "1.0.0"
            assert row["url"].startswith("/samples/university-town/")
    assert client.get("/api/layers").json() == []


def test_campus_switch_changes_only_default_asset_bindings_and_keeps_default_state(client):
    original = {row["id"]: row for row in catalog(client)}
    response = client.patch("/api/layers/catalog/demo-roads/map-state", json={"map_attached": False, "map_visible": False, "map_opacity": 0.4})
    assert response.status_code == 200, response.text
    alternate = {row["id"]: row for row in catalog(client, "huangpu")}
    assert alternate.keys() == original.keys()
    assert alternate["demo-roads"]["asset"] != original["demo-roads"]["asset"]
    assert alternate["demo-roads"]["url"].startswith("/samples/huangpu/")
    assert not alternate["demo-roads"]["map_attached"] and not alternate["demo-roads"]["map_visible"]
    assert alternate["demo-roads"]["map_opacity"] == 0.4
    with TestClient(app) as restarted:
        restored = {row["id"]: row for row in catalog(restarted)}
    assert not restored["demo-roads"]["map_attached"] and restored["demo-roads"]["map_opacity"] == 0.4
    assert len(restored) == 6


def test_custom_registration_joins_catalog_and_state_is_compatible_with_legacy_api(client):
    catalog(client)
    layer = upload(client, json.dumps(GEO).encode()).json()
    layer = client.patch(f"/api/layers/{layer['id']}", json={"name": "自定义道路", "type": "geojson", "category": "道路", "url": layer["url"]}).json()
    row = next(row for row in catalog(client) if row["id"] == layer["id"])
    assert row["category"] == "道路" and not row["builtin"] and row["asset"]["asset_id"] == layer["asset_id"]
    assert row["unit"] is None and row["legend"] == []
    response = client.patch(f"/api/layers/catalog/{layer['id']}/map-state", json={"map_attached": True, "map_visible": False, "map_opacity": 0.3, "order": 1})
    assert response.status_code == 200, response.text
    refreshed = catalog(client)
    assert refreshed[1]["id"] == layer["id"]
    legacy = client.get("/api/layers").json()[0]
    assert legacy["map_attached"] and not legacy["map_visible"] and legacy["map_opacity"] == 0.3
    client.patch(f"/api/layers/{layer['id']}/map-state", json={"map_visible": True})
    assert next(row for row in catalog(client) if row["id"] == layer["id"])["map_visible"]
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    assert len(catalog(client)) == 6


def test_catalog_rejects_unknown_ids_bad_campus_and_three_dimensional_reorder(client):
    catalog(client)
    assert client.patch("/api/layers/catalog/absent/map-state", json={"map_visible": False}).status_code == 404
    assert client.get("/api/layers/catalog?campus=absent").status_code == 422
    response = client.patch("/api/layers/catalog/demo-buildings/map-state", json={"order": 0})
    assert response.status_code == 422 and response.json()["code"] == "ORDER_UNSUPPORTED"
    for payload in ({"map_opacity": 1.1}, {"order": -1}, {"order": None}, {"order": 100}, {"map_visible": None}):
        assert client.patch("/api/layers/catalog/demo-roads/map-state", json=payload).status_code == 422


def test_referencing_builtin_entry_protects_versions_and_removing_registration_keeps_library(client):
    row = next(row for row in catalog(client) if row["id"] == "demo-points")
    response = client.post("/api/layers", json={"name": "复用默认样例", "type": "geojson", "url": row["url"]})
    assert response.status_code == 201, response.text
    layer = response.json()
    assert layer["asset_id"] == row["asset"]["asset_id"] and layer["asset_version"] == "1.0.0"
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 403
    assert client.get(f"http://testserver{row['url']}").status_code == 200
    duplicate = client.post("/api/assets/register", json={"name": "默认入口重复登记", "type": "geojson", "location": "http://localhost:8000" + row["url"]})
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["asset_id"] == layer["asset_id"]
    assert next(row for row in catalog(client) if row["id"] == "demo-points")["asset"]["asset_id"] == layer["asset_id"]
    for location in ("/samples/../private.json", "/samples/unknown/data.geojson"):
        assert client.post("/api/layers", json={"name": "非法入口", "type": "geojson", "url": location}).status_code == 422


def test_startup_computes_order_capability_after_backfilling_legacy_asset_binding(client):
    identity, layer_id = str(uuid4()), str(uuid4())
    folder = FILES_DIR / identity
    folder.mkdir()
    (folder / "data.geojson").write_text(json.dumps(GEO), encoding="utf-8")
    with SessionLocal() as session:
        session.add(Layer(id=layer_id, name="旧二维图层", category="专题", type="geojson",
                          url=f"/data-files/{identity}/data.geojson", source=""))
        session.commit()
    with TestClient(app) as restarted:
        row = next(row for row in catalog(restarted) if row["id"] == layer_id)
    assert row["asset"]["asset_id"] == identity and row["orderable"]


def test_point_height_attribute_does_not_make_a_two_dimensional_layer_extruded(client):
    data = {**GEO, "features": [{**GEO["features"][0], "properties": {"map_extrude_height_m": 20}}]}
    layer = upload(client, json.dumps(data).encode()).json()
    row = next(row for row in catalog(client) if row["id"] == layer["id"])
    assert row["orderable"]


def test_extruded_polygon_and_unread_external_geometry_keep_depth_ordering(client):
    data = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"map_extrude_height_m": 20},
            "geometry": {"type": "Polygon", "coordinates": [[[113, 23], [114, 23], [114, 24], [113, 23]]]}}]}
    layer = upload(client, json.dumps(data).encode()).json()
    remote = client.post("/api/layers", json={"name": "远程几何未知", "type": "geojson", "url": "https://example.invalid/geo.json"}).json()
    rows = {row["id"]: row for row in catalog(client)}
    assert not rows[layer["id"]]["orderable"] and not rows[remote["id"]]["orderable"]
    assert client.patch(f"/api/layers/catalog/{layer['id']}/map-state", json={"order": 0}).status_code == 422


@pytest.mark.parametrize("geometry", [
    {"type": "Point", "coordinates": [113, 23, 10]},
    {"type": "LineString", "coordinates": [[113, 23, 10], [114, 24, 10]]},
    {"type": "Polygon", "coordinates": [[[113, 23, 10], [114, 23, 10], [114, 24, 10], [113, 23, 10]]]},
])
def test_explicit_xyz_geometry_keeps_depth_and_rejects_ground_reordering(client, geometry):
    data = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geometry}]}
    response = upload(client, json.dumps(data).encode())
    assert response.status_code == 201, response.text
    layer = response.json()
    row = next(row for row in catalog(client) if row["id"] == layer["id"])
    assert not row["orderable"]
    result = client.patch(f"/api/layers/catalog/{layer['id']}/map-state", json={"order": 0})
    assert result.status_code == 422 and result.json()["code"] == "ORDER_UNSUPPORTED"
    published = client.get(layer["url"]).json()
    assert published["features"][0]["geometry"] == geometry

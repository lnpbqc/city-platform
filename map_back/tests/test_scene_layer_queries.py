from copy import deepcopy

import pytest

from app.database import SessionLocal
from app.models import Asset, AssetVersion, Layer
from app.object_index import index_asset
from test_objects import uploaded
from test_scenes import draft, layer_state
from test_timeseries import TIMES, custom_snapshot


@pytest.mark.parametrize("change", ["removed", "rebound", "unbound", "version"])
def test_saved_scene_queries_keep_exact_old_layer_binding_after_global_catalog_changes(client, change):
    layer = custom_snapshot(client)
    scene = client.post("/api/scenes", json={**draft(), "layers": [layer_state(layer)]}).json()
    pinned = {"layer_id": layer["id"], "asset_id": layer["asset_id"], "version": "1.0.0"}
    before = client.get("/api/objects", params=pinned).json()
    if change == "removed":
        assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    elif change in {"rebound", "unbound"}:
        url = uploaded(client)["url"] if change == "rebound" else "https://example.invalid/unread.geojson"
        updated = client.patch(f"/api/layers/{layer['id']}", json={"name": "全局新绑定", "type": "geojson", "url": url})
        assert updated.status_code == 200, updated.text
    else:
        with SessionLocal() as session:
            old = session.get(AssetVersion, (layer["asset_id"], "1.0.0"))
            new = AssetVersion(**{column.name: deepcopy(getattr(old, column.name)) for column in AssetVersion.__table__.columns if column.name != "version"}, version="2.0.0")
            session.add(new)
            session.flush()
            asset = session.get(Asset, layer["asset_id"])
            asset.current_version = "2.0.0"
            session.get(Layer, layer["id"]).asset_version = "2.0.0"
            index_asset(session, asset, new)
            session.commit()
    result = client.get("/api/objects", params=pinned)
    assert result.status_code == 200, result.text
    assert result.json() == before
    assert client.get("/api/objects/summary", params=pinned).json()["total"] == before["total"]
    query = {**pinned, "time": TIMES[0], "bbox": "0,0,1,1"}
    objects = client.get("/api/objects", params=query)
    assert objects.status_code == 200 and objects.json()["total"] == 3, objects.text
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    selected = client.post("/api/objects/select", json={**query, "geometry": geometry})
    assert selected.status_code == 200 and selected.json()["total"] == 3
    times = client.get(f"/api/layers/{layer['id']}/times", params={key: value for key, value in pinned.items() if key != "layer_id"})
    assert times.status_code == 200 and times.json() == [TIMES[0]], times.text
    series = client.get("/api/timeseries", params=query)
    assert series.status_code == 200 and len(series.json()["items"]) == 3, series.text
    assert {item["object_id"] for item in series.json()["items"]} == {item["object_id"] for item in objects.json()["items"]}
    assert all(item["asset"] == {"asset_id": layer["asset_id"], "version": "1.0.0"} for item in objects.json()["items"])
    assert client.delete(f"/api/scenes/{scene['id']}", headers={"If-Match": '"1"'}).status_code == 204
    expected = 404 if change == "removed" else 409 if change == "unbound" else 422
    for path, params in (("/api/objects", pinned), ("/api/timeseries", query)):
        assert client.get(path, params=params).status_code == expected


def test_scene_reference_to_asset_does_not_authorize_a_different_layer_id(client):
    layer = custom_snapshot(client)
    other = uploaded(client)
    saved = {**layer_state(layer), "layer_id": "captured-different-id"}
    response = client.post("/api/scenes", json={**draft(), "layers": [saved]})
    assert response.status_code == 201, response.text
    reference = {"asset_id": layer["asset_id"], "version": "1.0.0"}
    for path, query in (("/api/objects", {"layer_id": other["id"], **reference}),
                        ("/api/timeseries", {"layer_id": other["id"], "time": TIMES[0], **reference})):
        result = client.get(path, params=query)
        assert result.status_code == 422 and result.json()["code"] == "VALIDATION_ERROR"
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    assert client.get("/api/objects", params={"layer_id": layer["id"], **reference}).status_code == 404
    assert client.get("/api/objects", params={"layer_id": "captured-different-id", **reference}).status_code == 200

import json

from test_scenes import draft, layer_state


def point(name, coordinates):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": coordinates},
            "properties": {"name": name, "category": "交通", "custom": {"keep": True}}}


def data_file(*features):
    return ("poi.geojson", json.dumps({"type": "FeatureCollection", "features": features}), "application/geo+json")


def test_poi_import_rejects_non_point_features(client):
    feature = point("道路", [121.5, 25.0])
    feature["geometry"] = {"type": "LineString", "coordinates": [[121.5, 25.0], [121.6, 25.0]]}
    result = client.post("/api/layers/upload", data={"name": "POI", "category": "POI", "type": "geojson"},
                         files={"file": data_file(feature)})
    assert result.status_code == 422


def test_poi_snapshot_rebinds_only_current_layer_and_rejects_stale_save(client):
    initial = point("原有点", [121.5, 25.0])
    uploaded = client.post("/api/layers/upload", data={"name": "POI", "category": "POI", "type": "geojson"},
                           files={"file": data_file(initial)})
    assert uploaded.status_code == 201, uploaded.text
    layer = uploaded.json()
    attached = client.patch(f"/api/layers/catalog/{layer['id']}/map-state", json={"map_attached": True})
    assert attached.status_code == 200, attached.text
    assert attached.json()["category"] == "POI"
    scene = client.post("/api/scenes", json={**draft(), "layers": [layer_state(layer)]})
    assert scene.status_code == 201, scene.text
    path = f"/api/layers/{layer['id']}/poi-data"
    expected = {"asset_id": layer["asset_id"], "version": layer["asset_version"]}

    invalid = client.put(path, data=expected, files={"file": data_file(point("越界", [200, 25]))})
    assert invalid.status_code == 422, invalid.text
    updated = point("改名", [121.55, 25.01])
    result = client.put(path, data=expected, files={"file": data_file(updated)})
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved["id"] == layer["id"] and saved["asset_id"] != layer["asset_id"]
    assert saved["map_attached"]
    assert client.get(saved["url"]).json()["features"] == [updated]
    assert client.get(layer["url"]).json()["features"] == [initial]

    previous = client.get("/api/objects", params={"layer_id": layer["id"], **expected})
    assert previous.status_code == 200 and previous.json()["items"][0]["name"] == "原有点"
    current = client.get("/api/objects", params={"layer_id": layer["id"], "q": "改名"})
    assert current.status_code == 200 and current.json()["items"][0]["properties"]["custom"] == {"keep": True}
    stale = client.put(path, data=expected, files={"file": data_file()})
    assert stale.status_code == 409 and stale.json()["code"] == "POI_SNAPSHOT_CONFLICT"
    cleared = client.put(path, data={"asset_id": saved["asset_id"], "version": saved["asset_version"]},
                         files={"file": data_file()})
    assert cleared.status_code == 200 and client.get(cleared.json()["url"]).json()["features"] == []

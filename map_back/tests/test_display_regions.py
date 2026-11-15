from fastapi.testclient import TestClient

from app.main import app


def test_display_regions_are_seeded_once_and_shared_across_clients(client):
    path = "/api/display-regions"
    response = client.get(path)
    assert response.status_code == 200
    seeded = {row["name"]: row for row in response.json()}
    assert {name: row["radius_m"] for name, row in seeded.items()} == {
        "香港维港": 5000, "广州珠江新城": 4000, "大学城校区": 2000, "黄埔校区": 2000,
    }
    assert seeded["黄埔校区"]["camera"]["scene_mode"] == "3d"
    view = {
        "camera": {"longitude": 113.37, "latitude": 23.04, "height": 4050,
                   "heading": 0, "pitch": -1.57, "roll": 0, "scene_mode": "2d"},
        "longitude": 113.37, "latitude": 23.04, "radius_m": 1800,
    }
    created = client.post(path, json={"name": "我的视角", **view})
    assert created.status_code == 201
    region_path = f'{path}/{created.json()["id"]}'
    assert client.patch(region_path, json={"name": "正门"}).json()["camera"] == view["camera"]
    assert client.patch(region_path, json={"radius_m": 30}).status_code == 422
    assert client.patch(region_path, json={**view, "radius_m": 2200}).json()["radius_m"] == 2200
    assert client.post(path, json={"name": "全国", **view, "radius_m": 25000}).status_code == 422
    assert client.delete(f'{path}/{seeded["香港维港"]["id"]}').status_code == 204
    with TestClient(app) as second:
        rows = second.get(path).json()
    assert {row["name"] for row in rows} == {"广州珠江新城", "大学城校区", "黄埔校区", "正门"}
    assert next(row for row in rows if row["name"] == "正门")["camera"] == view["camera"]

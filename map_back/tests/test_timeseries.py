from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math

from fastapi.testclient import TestClient
import pytest
from shapely.geometry import shape
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import IntegrityError

from app.builtin_assets import CAMPUS_KEYS, SAMPLES_DIR, builtin_asset_id
from app.database import SessionLocal, engine
from app.layer_catalog import initialize_catalog
from app.main import app
from app.models import Asset, AssetVersion, SpatialObject, TimeSeriesSnapshot
from app.object_index import index_asset, object_id
from app.timeseries import ensure_timeseries, normalized_time, safe_average, utc_text
from test_objects import features, uploaded

TIMES = ["2026-10-25T00:00:00Z", "2026-10-25T01:00:00Z", "2026-10-26T00:00:00Z", "2026-10-26T01:00:00Z"]


@pytest.fixture
def temporal_client(client):
    with SessionLocal() as session:
        initialize_catalog(session)
        ensure_timeseries(session)
        session.commit()
    return client


def series(client, layer_id="demo-points", **params):
    response = client.get("/api/timeseries", params={"layer_id": layer_id, "time": TIMES[0], **params})
    assert response.status_code == 200, response.text
    return response.json()


def values_by_feature(document, identity, version="1.0.0", count=3):
    items = {item["object_id"]: item for item in document["items"]}
    return [items[object_id(identity, version, index)] for index in range(count)]


def sample_hashes():
    return {path.relative_to(SAMPLES_DIR).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in SAMPLES_DIR.rglob("*") if path.is_file()}


def custom_snapshot(client, data=None, values=None):
    layer = uploaded(client, data or features())
    with SessionLocal() as session:
        objects = list(session.scalars(select(SpatialObject).where(SpatialObject.asset_id == layer["asset_id"]).order_by(SpatialObject.feature_index)))
        numbers = values or [0, 10, None, 0]
        session.add(TimeSeriesSnapshot(asset_id=layer["asset_id"], asset_version="1.0.0", unit="cm",
                    document={TIMES[0]: {row.id: numbers[index] for index, row in enumerate(objects)}}))
        session.commit()
    return layer


@pytest.mark.parametrize("campus", CAMPUS_KEYS)
@pytest.mark.parametrize("layer_id,unit,count", [("demo-points", "cm", 3), ("demo-roads", "辆/小时", 2), ("demo-areas", "cm", 1)])
def test_default_times_are_ascending_utc_and_asset_scoped(temporal_client, campus, layer_id, unit, count):
    client = temporal_client
    identity = builtin_asset_id(campus, layer_id)
    params = {"asset_id": identity, "version": "1.0.0", "campus": campus}
    response = client.get(f"/api/layers/{layer_id}/times", params=params)
    assert response.status_code == 200 and response.json() == TIMES
    result = series(client, layer_id, **params)
    assert result["asset"] == {"asset_id": identity, "version": "1.0.0"}
    assert result["time"] == TIMES[0] and result["resolution"] == "hour" and result["unit"] == unit
    assert len(result["items"]) == count
    first = values_by_feature(result, identity, count=count)
    assert first[0]["value"] == 0 and first[0]["missing"] is False and first[0]["geometry"] is not None
    if count > 1:
        assert first[1]["value"] is None and first[1]["missing"] and first[1]["geometry"] is None


def test_hour_is_exact_and_timezone_equivalent_but_never_uses_nearest_or_zero_fill(temporal_client):
    client = temporal_client
    original = series(client)
    assert series(client, time="2026-10-25T08:00:00+08:00") == original
    assert series(client, time="2026-10-24T20:00:00-04:00") == original
    between = series(client, time="2026-10-25T08:00:01+08:00")
    assert between["time"] == "2026-10-25T00:00:01Z"
    assert all(item["value"] is None and item["missing"] and item["geometry"] is None for item in between["items"])
    absent = series(client, time="2026-10-24T00:00:00Z")
    assert all(item["missing"] for item in absent["items"])


def test_daily_means_use_shanghai_calendar_nonnull_hours_and_preserve_an_entire_missing_day(temporal_client):
    client = temporal_client
    identity = builtin_asset_id("university-town", "demo-points")
    first = series(client, time="2026-10-25T15:59:59Z", resolution="day")
    assert first["time"] == "2026-10-24T16:00:00Z"
    assert [item["value"] for item in values_by_feature(first, identity)] == [5, 12, 10]
    second = series(client, time="2026-10-25T16:00:00Z", resolution="day")
    assert second["time"] == "2026-10-25T16:00:00Z"
    second_values = values_by_feature(second, identity)
    assert [item["value"] for item in second_values] == [25, 27, None]
    assert second_values[2]["missing"] and second_values[2]["geometry"] is None
    area = series(client, "demo-areas", time=TIMES[2], resolution="day")
    assert area["items"][0]["missing"] and area["items"][0]["value"] is None
    roads = series(client, "demo-roads", time=TIMES[0], resolution="day")
    assert [item["value"] for item in values_by_feature(roads, builtin_asset_id("university-town", "demo-roads"), count=2)] == [50, 120]


def test_daily_clock_uses_iana_shanghai_history_and_safe_mean_never_overflows():
    assert utc_text(normalized_time(datetime.fromisoformat("1991-07-01T12:00:00+09:00"), "day")) == "1991-06-30T15:00:00Z"
    maximum = float.fromhex("0x1.fffffffffffffp+1023")
    assert safe_average([maximum, maximum, maximum]) == maximum
    assert safe_average([maximum, -maximum]) == 0
    assert math.isfinite(safe_average([1e308, 1e308]))
    assert safe_average([]) is None and safe_average([0, 0]) == 0


def test_daily_api_averages_extreme_finite_observations_safely(client):
    layer = uploaded(client)
    identity = object_id(layer["asset_id"], "1.0.0", 0)
    with SessionLocal() as session:
        session.add(TimeSeriesSnapshot(asset_id=layer["asset_id"], asset_version="1.0.0", unit="cm",
                    document={time: {identity: 1e308} for time in TIMES[:2]}))
        session.commit()
    result = series(client, layer["id"], resolution="day")
    assert next(item for item in result["items"] if item["object_id"] == identity)["value"] == 1e308


def test_bbox_uses_actual_clipping_and_keeps_spatially_selected_missing_objects(client):
    layer = custom_snapshot(client)
    result = series(client, layer["id"], bbox="0,0,1,1")
    by_id = {item["object_id"]: item for item in result["items"]}
    assert len(by_id) == 3
    road = by_id[object_id(layer["asset_id"], "1.0.0", 1)]
    assert road["geometry"]["coordinates"] == [[0, 0.5], [1, 0.5]]
    assert road["value"] == 10 and not road["missing"]
    missing = by_id[object_id(layer["asset_id"], "1.0.0", 2)]
    assert missing["value"] is None and missing["geometry"] is None and missing["missing"]
    assert series(client, layer["id"], bbox="10,10,11,11")["items"] == []
    original = client.get(f"/api/objects/{road['object_id']}").json()
    assert original["geometry"]["coordinates"] == [[-2, 0.5], [2, 0.5]]
    assert shape(client.get(f"/api/objects/{missing['object_id']}").json()["geometry"]).bounds == (-1, -1, 2, 2)


def test_bbox_rejects_hole_false_positives_and_selects_missing_by_original_geometry(client):
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
                  [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]]]}
    layer = custom_snapshot(client, {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geometry}]}, [None])
    assert series(client, layer["id"], bbox="1.5,1.5,2.5,2.5")["items"] == []
    selected = series(client, layer["id"], bbox="0,0,0.5,0.5")["items"]
    assert len(selected) == 1 and selected[0]["missing"] and selected[0]["geometry"] is None


def test_object_time_fields_match_series_without_overwriting_properties_or_detail_geometry(temporal_client):
    client = temporal_client
    identity = builtin_asset_id("university-town", "demo-points")
    original = client.get("/api/objects", params={"asset_id": identity}).json()
    hourly = client.get("/api/objects", params={"asset_id": identity, "time": TIMES[0]}).json()
    baseline = {item["object_id"]: item for item in original["items"]}
    values = {item["object_id"]: item for item in series(client)["items"]}
    for item in hourly["items"]:
        assert item["properties"] == baseline[item["object_id"]]["properties"]
        assert item["geometry"] == baseline[item["object_id"]]["geometry"]
        assert item["temporal"] == {"time": TIMES[0], "resolution": "hour", "unit": "cm",
                                    "value": values[item["object_id"]]["value"], "missing": values[item["object_id"]]["missing"]}
        detail = client.get(f"/api/objects/{item['object_id']}", params={"time": TIMES[0]}).json()
        assert detail == item
    assert all(item["temporal"] is None for item in original["items"])
    first = object_id(identity, "1.0.0", 0)
    daily = client.get(f"/api/objects/{first}", params={"time": TIMES[1], "resolution": "day"}).json()
    assert daily["temporal"] == {"time": "2026-10-24T16:00:00Z", "resolution": "day", "unit": "cm", "value": 5, "missing": False}
    polygon = {"type": "Polygon", "coordinates": [[[113, 22], [114, 22], [114, 24], [113, 24], [113, 22]]]}
    selection = client.post("/api/objects/select", json={"asset_id": identity, "time": TIMES[1], "resolution": "day", "geometry": polygon})
    assert selection.status_code == 200 and selection.json()["total"] == 3
    assert all(item["temporal"]["time"] == "2026-10-24T16:00:00Z" for item in selection.json()["items"])


def test_static_layers_have_no_times_or_temporal_values_and_do_not_invent_series(temporal_client):
    client = temporal_client
    layer = uploaded(client)
    remote = client.post("/api/layers", json={"name": "外部静态", "type": "geojson", "url": "https://example.invalid/static.geojson"}).json()
    for layer_id in ("basemap", "campus-buildings", "demo-buildings", layer["id"], remote["id"]):
        response = client.get(f"/api/layers/{layer_id}/times")
        assert response.status_code == 200 and response.json() == []
        response = client.get("/api/timeseries", params={"layer_id": layer_id, "time": TIMES[0]})
        assert response.status_code == 409 and response.json()["code"] == "TIMESERIES_UNAVAILABLE"
    objects = client.get("/api/objects", params={"layer_id": layer["id"], "time": TIMES[0]}).json()["items"]
    assert all(item["temporal"] is None for item in objects)


def test_old_series_stays_pinned_when_current_version_has_no_observations(temporal_client):
    client = temporal_client
    identity = builtin_asset_id("university-town", "demo-points")
    with SessionLocal() as session:
        original = session.get(AssetVersion, (identity, "1.0.0"))
        new = AssetVersion(**{column.name: deepcopy(getattr(original, column.name)) for column in AssetVersion.__table__.columns if column.name != "version"}, version="2.0.0")
        session.add(new)
        session.flush()
        asset = session.get(Asset, identity)
        asset.current_version = "2.0.0"
        index_asset(session, asset, new)
        session.commit()
    assert client.get("/api/layers/demo-points/times").json() == []
    params = {"asset_id": identity, "version": "1.0.0", "campus": "university-town"}
    assert client.get("/api/layers/demo-points/times", params=params).json() == TIMES
    assert series(client, **params)["asset"]["version"] == "1.0.0"
    latest = client.get("/api/timeseries", params={"layer_id": "demo-points", "time": TIMES[0], "version": "2.0.0"})
    assert latest.status_code == 409 and latest.json()["code"] == "TIMESERIES_UNAVAILABLE"
    catalog = {item["id"]: item for item in client.get("/api/layers/catalog").json()}
    assert catalog["demo-points"]["static"] is True


def test_catalog_marks_only_observed_versions_dynamic_and_exposes_matching_legends(temporal_client):
    rows = {item["id"]: item for item in temporal_client.get("/api/layers/catalog").json()}
    assert {identity for identity, item in rows.items() if not item["static"]} == {"demo-points", "demo-roads", "demo-areas"}
    colors = ["#dbeafe", "#93c5fd", "#3b82f6", "#1d4ed8", "#94a3b8"]
    assert [item["color"] for item in rows["demo-points"]["legend"]] == colors
    assert [item["label"] for item in rows["demo-roads"]["legend"]] == ["0 辆/小时", "0–100 辆/小时", "100–300 辆/小时", ">300 辆/小时", "缺测"]
    assert rows["demo-points"]["legend"][3]["value"] == "32–32"
    assert rows["demo-roads"]["unit"] == "辆/小时"


def test_startup_is_idempotent_preserves_original_ids_urls_fingerprints_and_published_files(temporal_client):
    client = temporal_client
    before_files = sample_hashes()
    with SessionLocal() as session:
        before = {(row.asset_id, row.asset_version): (row.unit, deepcopy(row.document)) for row in session.scalars(select(TimeSeriesSnapshot))}
        assets = {(row.id, row.current_version): row.entry_url for row in session.scalars(select(Asset))}
        fingerprints = {(row.asset_id, row.version): (row.sha256, deepcopy(row.file_manifest)) for row in session.scalars(select(AssetVersion))}
        ensure_timeseries(session)
        ensure_timeseries(session)
        session.commit()
    with TestClient(app) as restarted:
        assert restarted.get("/api/layers/demo-points/times").json() == TIMES
    with SessionLocal() as session:
        assert {(row.asset_id, row.asset_version): (row.unit, row.document) for row in session.scalars(select(TimeSeriesSnapshot))} == before
        assert {(row.id, row.current_version): row.entry_url for row in session.scalars(select(Asset))} == assets
        assert {(row.asset_id, row.version): (row.sha256, row.file_manifest) for row in session.scalars(select(AssetVersion))} == fingerprints
    assert len(before) == 6 and before_files == sample_hashes()


def test_time_reads_and_playback_issue_no_database_writes(temporal_client):
    statements = []
    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lstrip().split()[0].upper())
    event.listen(engine, "before_cursor_execute", capture)
    try:
        for time in TIMES:
            assert temporal_client.get("/api/layers/demo-points/times").status_code == 200
            series(temporal_client, time=time)
            assert temporal_client.get("/api/objects", params={"layer_id": "demo-points", "time": time}).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert not set(statements) & {"INSERT", "UPDATE", "DELETE", "REPLACE"}


def test_snapshot_update_is_rejected_and_version_foreign_keys_are_enforced(temporal_client):
    identity = builtin_asset_id("university-town", "demo-points")
    with SessionLocal() as session:
        with pytest.raises(IntegrityError, match="时序快照不可修改"):
            session.execute(update(TimeSeriesSnapshot).where(TimeSeriesSnapshot.asset_id == identity).values(unit="m"))
        session.rollback()
        session.add(TimeSeriesSnapshot(asset_id="absent", asset_version="1.0.0", unit="cm", document={}))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


@pytest.mark.parametrize("target", ["asset", "version"])
def test_released_asset_or_version_cascades_time_snapshot_without_protecting_unreferenced_files(client, target):
    layer = custom_snapshot(client)
    identity = layer["asset_id"]
    assert client.delete(f"/api/assets/{identity}").status_code == 409
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    if target == "asset":
        assert client.delete(f"/api/assets/{identity}").status_code == 204
    else:
        with SessionLocal() as session:
            session.delete(session.get(AssetVersion, (identity, "1.0.0")))
            session.commit()
    with SessionLocal() as session:
        assert session.get(TimeSeriesSnapshot, (identity, "1.0.0")) is None
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


@pytest.mark.parametrize("params,code,status", [
    ({"layer_id": "missing"}, "LAYER_NOT_FOUND", 404),
    ({"asset_id": "missing"}, "VALIDATION_ERROR", 422),
    ({"version": "missing"}, "ASSET_VERSION_NOT_FOUND", 404),
    ({"time": "2026-10-25T08:00:00"}, "VALIDATION_ERROR", 422),
    ({"time": "invalid"}, "VALIDATION_ERROR", 422),
    ({"resolution": "minute"}, "VALIDATION_ERROR", 422),
    ({"campus": "missing"}, "VALIDATION_ERROR", 422),
    ({"bbox": "1,1,2,0"}, "VALIDATION_ERROR", 422),
    ({"bbox": "NaN,0,1,1"}, "VALIDATION_ERROR", 422),
    ({"unexpected": "value"}, "VALIDATION_ERROR", 422),
])
def test_time_queries_validate_inputs_and_keep_existing_layer_asset_error_semantics(temporal_client, params, code, status):
    response = temporal_client.get("/api/timeseries", params={"layer_id": "demo-points", "time": TIMES[0], **params})
    assert response.status_code == status and response.json()["code"] == code, response.text


def test_custom_layer_binding_mismatches_and_object_temporal_query_validation(temporal_client):
    client = temporal_client
    layer = uploaded(client)
    response = client.get(f"/api/layers/{layer['id']}/times", params={"version": "2.0.0"})
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_ERROR"
    identity = object_id(builtin_asset_id("university-town", "demo-points"), "1.0.0", 0)
    for path in ("/api/objects", f"/api/objects/{identity}"):
        assert client.get(path, params={"time": "2026-10-25T00:00:00"}).status_code == 422
        assert client.get(path, params={"time": TIMES[0], "resolution": "minute"}).status_code == 422

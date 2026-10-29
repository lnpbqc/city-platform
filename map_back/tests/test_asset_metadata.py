import hashlib
import json
import math
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.asset_metadata import build_metadata


def write(root, document, name="data.geojson"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return [{"path": name, "size": path.stat().st_size}]


def bounds_for(tmp_path, volume, transform=None):
    root = {"boundingVolume": volume}
    if transform is not None:
        root["transform"] = transform
    files = write(tmp_path, {"asset": {"version": "1.1"}, "root": root}, "tileset.json")
    return build_metadata(tmp_path, files, "tileset.json", "3dtiles")["bounds"]


def test_nested_files_have_streamed_hashes_and_stable_manifest(tmp_path, monkeypatch):
    files = write(tmp_path, {"type": "FeatureCollection", "features": []})
    (tmp_path / "nested").mkdir()
    payload = b"0123456789" * 150000
    (tmp_path / "nested" / "模型.glb").write_bytes(payload)
    files.insert(0, {"path": "nested/模型.glb", "size": len(payload)})

    def no_whole_file_read(*args, **kwargs):
        raise AssertionError("文件哈希应使用分块读取")

    monkeypatch.setattr(Path, "read_bytes", no_whole_file_read)
    original_open = Path.open

    @contextmanager
    def bounded_open(path, mode="r", *args, **kwargs):
        with original_open(path, mode, *args, **kwargs) as stream:
            if "b" in mode:
                original_read = stream.read

                def bounded_read(size=-1):
                    assert 0 < size < len(payload), "二进制文件读取必须指定有限分块"
                    return original_read(size)

                stream.read = bounded_read
            yield stream

    monkeypatch.setattr(Path, "open", bounded_open)
    metadata = build_metadata(tmp_path, files, "data.geojson", "geojson")
    assert [item["path"] for item in metadata["files"]] == ["data.geojson", "nested/模型.glb"]
    assert metadata["files"][1] == {"path": "nested/模型.glb", "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    encoded = json.dumps(metadata["files"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    assert metadata["sha256"] == hashlib.sha256(encoded).hexdigest()
    assert build_metadata(tmp_path, list(reversed(files)), "data.geojson", "geojson") == metadata
    assert (tmp_path / "nested" / "模型.glb").stat().st_size == len(payload)


def test_geojson_uses_all_point_line_polygon_and_collection_coordinates(tmp_path):
    geometries = [
        {"type": "Point", "coordinates": [113, 23, 15]},
        {"type": "LineString", "coordinates": [[112, 22, 5], [114, 24, 25]]},
        {"type": "Polygon", "coordinates": [[[111, 21, 0], [115, 21, 1], [115, 25, 30], [111, 21, 0]]]},
        {"type": "GeometryCollection", "geometries": [{"type": "MultiPoint", "coordinates": [[110, 20, -2]]}]},
    ]
    files = write(tmp_path, {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geometry, "properties": {"ignored": [180, 90]}} for geometry in geometries]})
    assert build_metadata(tmp_path, files, "data.geojson", "geojson")["bounds"] == {
        "west": 110, "south": 20, "east": 115, "north": 25, "min_height": -2, "max_height": 30,
    }


def test_geojson_missing_height_remains_unknown_and_crosses_dateline(tmp_path):
    files = write(tmp_path, {"type": "MultiPoint", "coordinates": [[179, 20, 3], [-179, 22]]})
    bounds = build_metadata(tmp_path, files, "data.geojson", "geojson")["bounds"]
    assert bounds == {"west": 179, "south": 20, "east": -179, "north": 22, "min_height": None, "max_height": None}


@pytest.mark.parametrize("document", [
    {"type": "FeatureCollection", "features": []},
    {"type": "Point", "coordinates": [113, 91]},
    {"type": "Point", "coordinates": [float("nan"), 23]},
    {"type": "Point", "coordinates": [113, 23], "crs": {"type": "name", "properties": {"name": "EPSG:3857"}}},
    {"type": "Feature", "geometry": None},
])
def test_geojson_unknown_or_invalid_bounds_are_null(tmp_path, document):
    files = write(tmp_path, document)
    assert build_metadata(tmp_path, files, "data.geojson", "geojson")["bounds"] is None


def test_region_is_radians_and_ignores_transform(tmp_path):
    bounds = bounds_for(tmp_path, {"region": [math.radians(179), math.radians(20), math.radians(-179), math.radians(22), -5, 100]}, [0] * 16)
    assert bounds == pytest.approx({"west": 179, "south": 20, "east": -179, "north": 22, "min_height": -5, "max_height": 100})


def test_box_applies_column_major_root_transform(tmp_path):
    # At lon=0,lat=0: east=ECEF Y, north=ECEF Z, up=ECEF X.
    transform = [0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 6378237, 0, 0, 1]
    bounds = bounds_for(tmp_path, {"box": [0, 0, 0, 10, 0, 0, 0, 20, 0, 0, 0, 5]}, transform)
    assert bounds["west"] < 0 < bounds["east"]
    assert bounds["south"] < 0 < bounds["north"]
    assert bounds["east"] >= math.degrees(math.atan2(10, 6378232))
    assert bounds["min_height"] <= 95
    assert bounds["max_height"] >= 105


def test_box_bounds_include_north_face_and_bottom_face_centres(tmp_path):
    latitude = math.radians(45)
    sine, cosine = math.sin(latitude), math.cos(latitude)
    eccentricity = 6.6943799901413165e-3
    normal = 6378137 / math.sqrt(1 - eccentricity * sine * sine)
    transform = [0, 1, 0, 0, -sine, 0, cosine, 0, cosine, 0, sine, 0,
                 (normal + 1000) * cosine, 0, (normal * (1 - eccentricity) + 1000) * sine, 1]
    bounds = bounds_for(tmp_path, {"box": [0, 0, 0, 50000, 0, 0, 0, 50000, 0, 0, 0, 10]}, transform)
    # Bottom face centre is exactly 990 m at 45 degrees; the north face
    # midpoint projects farther north than any corner of this curved envelope.
    assert bounds["min_height"] <= 990
    assert bounds["north"] >= 45.44981934478846


def test_real_campus_sample_is_in_guangzhou_and_hashes_all_files():
    root = Path(__file__).resolve().parents[2] / "map/public/samples/university-town/buildings"
    files = [{"path": path.relative_to(root).as_posix(), "size": path.stat().st_size} for path in root.rglob("*") if path.is_file()]
    result = build_metadata(root, files, "tileset.json", "3dtiles")
    bounds = result["bounds"]
    assert 113 < bounds["west"] < bounds["east"] < 114
    assert 22 < bounds["south"] < bounds["north"] < 24
    assert bounds["west"] < 113.366746 < bounds["east"]
    assert bounds["south"] < 23.043612 < bounds["north"]
    assert bounds["min_height"] <= 11
    assert bounds["max_height"] >= 121
    assert {item["path"] for item in result["files"]} == {"tileset.json", "buildings.glb"}


def test_transformed_sphere_has_conservative_geographic_bounds(tmp_path):
    transform = [2, 0, 0, 0, 0, 3, 0, 0, 0, 0, 4, 0, 6378237, 0, 0, 1]
    bounds = bounds_for(tmp_path, {"sphere": [0, 0, 0, 10]}, transform)
    assert bounds["west"] < 0 < bounds["east"]
    assert bounds["south"] < 0 < bounds["north"]
    assert bounds["min_height"] <= 60
    assert bounds["max_height"] >= 140


@pytest.mark.parametrize("volume,transform", [
    ({"sphere": [0, 0, 0, 10]}, None),
    ({"box": [0, 0, 0, 10, 0, 0, 0, 10, 0, 0, 0, 10]}, None),
    ({"region": [0, 2, 1, 3, 0, 10]}, None),
    ({"region": [0, 0, 1, 1, 20, 10]}, None),
    ({"sphere": [6378137, 0, 0, -1]}, None),
    ({"box": [6378137, 0, 0]}, None),
    ({"sphere": [0, 0, 0, 10]}, [1, 2]),
    ({"unknown": []}, None),
    ({"region": [0, 0, 1, 1, 0, 10], "sphere": [6378137, 0, 0, 10]}, None),
])
def test_unregistered_or_invalid_tiles_bounds_are_null(tmp_path, volume, transform):
    assert bounds_for(tmp_path, volume, transform) is None


def test_unknown_format_still_hashes_all_files(tmp_path):
    files = write(tmp_path, {"anything": "retained"}, "other.json")
    result = build_metadata(tmp_path, files, "other.json", "unknown")
    assert result["bounds"] is None
    assert result["files"][0]["sha256"]

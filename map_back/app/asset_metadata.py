"""Read-only file checksums and geographic bounds for published assets."""

import hashlib
import itertools
import json
import math
from pathlib import Path

_A = 6378137.0
_E2 = 6.6943799901413165e-3
_B = _A * math.sqrt(1 - _E2)
_IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def _numbers(values, length):
    return (isinstance(values, list) and len(values) == length
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in values))


def _longitude_range(values):
    values = sorted(set(values))
    if len(values) == 1:
        return values[0], values[0]
    gaps = [values[index + 1] - value for index, value in enumerate(values[:-1])]
    gaps.append(values[0] + 360 - values[-1])
    index = max(range(len(gaps)), key=gaps.__getitem__)
    return values[(index + 1) % len(values)], values[index]


def _bounds(positions):
    if not positions:
        return None
    west, east = _longitude_range([point[0] for point in positions])
    heights = [point[2] for point in positions if len(point) > 2]
    all_heights = len(heights) == len(positions)
    return {"west": west, "south": min(point[1] for point in positions),
            "east": east, "north": max(point[1] for point in positions),
            "min_height": min(heights) if all_heights else None,
            "max_height": max(heights) if all_heights else None}


def _geojson_bounds(document):
    positions = []
    depths = {"Point": 0, "MultiPoint": 1, "LineString": 1,
              "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}

    def coordinates(value, depth):
        if depth:
            if not isinstance(value, list):
                raise ValueError("Invalid coordinates")
            for item in value:
                coordinates(item, depth - 1)
        else:
            if not isinstance(value, list) or len(value) < 2 or not _numbers(value, len(value)):
                raise ValueError("Invalid position")
            if not -180 <= value[0] <= 180 or not -90 <= value[1] <= 90:
                raise ValueError("Coordinates are not WGS84")
            positions.append(value[:3])

    def visit(value):
        if value is None:
            return
        if not isinstance(value, dict) or "crs" in value:
            raise ValueError("Unsupported geometry or CRS")
        kind = value.get("type")
        if kind == "Feature":
            visit(value.get("geometry"))
        elif kind in ("FeatureCollection", "GeometryCollection"):
            key = "features" if kind == "FeatureCollection" else "geometries"
            children = value.get(key)
            if not isinstance(children, list):
                raise ValueError("Invalid collection")
            for child in children:
                visit(child)
        elif kind in depths:
            coordinates(value.get("coordinates"), depths[kind])
        else:
            raise ValueError("Unsupported geometry")

    visit(document)
    return _bounds(positions)


def _transform_point(matrix, point):
    return [sum(matrix[row + 4 * column] * point[column] for column in range(3)) + matrix[row + 12]
            for row in range(3)]


def _ecef_position(point):
    x, y, z = point
    if not all(math.isfinite(value) for value in point) or math.hypot(x, y, z) < _B / 2:
        raise ValueError("Bounding volume has no Earth-centred placement")
    horizontal = math.hypot(x, y)
    if horizontal < 1e-8:
        return [0, math.copysign(90, z), abs(z) - _B]
    latitude = math.atan2(z, horizontal * (1 - _E2))
    for _ in range(12):
        normal = _A / math.sqrt(1 - _E2 * math.sin(latitude) ** 2)
        updated = math.atan2(z + _E2 * normal * math.sin(latitude), horizontal)
        if abs(updated - latitude) < 1e-14:
            latitude = updated
            break
        latitude = updated
    normal = _A / math.sqrt(1 - _E2 * math.sin(latitude) ** 2)
    height = (horizontal / math.cos(latitude) - normal if abs(math.cos(latitude)) > 1e-6
              else z / math.sin(latitude) - normal * (1 - _E2))
    return [math.degrees(math.atan2(y, x)), math.degrees(latitude), height]


def _sphere_bounds(center, radius):
    longitude, latitude, height = _ecef_position(center)
    if math.hypot(*center) - radius < _B / 2:
        return None
    # Geodetic latitude gradient is bounded by the smallest meridian radius
    # of curvature plus the smallest height within the enclosing sphere.
    latitude_delta = math.degrees(radius / (_A * (1 - _E2) + height - radius))
    horizontal = math.hypot(*center[:2])
    south, north = max(-90, latitude - latitude_delta), min(90, latitude + latitude_delta)
    if radius >= horizontal or south == -90 or north == 90:
        west, east = -180, 180
    else:
        longitude_delta = math.degrees(math.asin(radius / horizontal))
        west = (longitude - longitude_delta + 180) % 360 - 180
        east = (longitude + longitude_delta + 180) % 360 - 180
    return {"west": west, "south": south, "east": east, "north": north,
            "min_height": height - radius, "max_height": height + radius}


def _tiles_bounds(document):
    root = document.get("root")
    if not isinstance(root, dict) or not isinstance(root.get("boundingVolume"), dict):
        return None
    volume = root["boundingVolume"]
    if sum(key in volume for key in ("region", "box", "sphere")) != 1:
        return None
    if "region" in volume:
        region = volume["region"]
        if (not _numbers(region, 6) or not -math.pi <= region[0] <= math.pi
                or not -math.pi <= region[2] <= math.pi
                or not -math.pi / 2 <= region[1] <= region[3] <= math.pi / 2
                or region[4] > region[5]):
            return None
        return dict(zip(("west", "south", "east", "north", "min_height", "max_height"),
                        [math.degrees(value) for value in region[:4]] + region[4:]))
    matrix = root.get("transform", _IDENTITY)
    if not _numbers(matrix, 16) or [matrix[index] for index in (3, 7, 11, 15)] != [0, 0, 0, 1]:
        return None
    if "box" in volume:
        box = volume["box"]
        if not _numbers(box, 12):
            return None
        center = _transform_point(matrix, box[:3])
        radius = 0
        for signs in itertools.product((-1, 1), repeat=3):
            point = [box[axis] + sum(signs[index] * box[3 + index * 3 + axis] for index in range(3)) for axis in range(3)]
            radius = max(radius, math.dist(center, _transform_point(matrix, point)))
        # The transformed box lies inside the sphere enclosing all its corners;
        # converting only corners misses latitude/height extrema on its faces.
        return _sphere_bounds(center, radius)
    if "sphere" in volume:
        sphere = volume["sphere"]
        if not _numbers(sphere, 4) or sphere[3] < 0:
            return None
        # sqrt(||A||1 * ||A||inf) bounds the spectral norm, including shear.
        column_norm = max(sum(abs(matrix[row + 4 * column]) for row in range(3)) for column in range(3))
        row_norm = max(sum(abs(matrix[row + 4 * column]) for column in range(3)) for row in range(3))
        radius = sphere[3] * math.sqrt(column_norm * row_norm)
        return _sphere_bounds(_transform_point(matrix, sphere[:3]), radius)
    return None


def build_metadata(root: Path, files: list[dict], entry_relative: str, kind: str) -> dict:
    manifest = []
    for item in sorted(files, key=lambda value: value["path"]):
        digest = hashlib.sha256()
        size = 0
        with (root / item["path"]).open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        manifest.append({"path": item["path"], "size": size, "sha256": digest.hexdigest()})
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    bounds = None
    if kind in ("geojson", "3dtiles"):
        try:
            with (root / entry_relative).open(encoding="utf-8-sig") as stream:
                document = json.load(stream)
            if isinstance(document, dict):
                bounds = _geojson_bounds(document) if kind == "geojson" else _tiles_bounds(document)
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            bounds = None
    return {"files": manifest, "sha256": hashlib.sha256(encoded).hexdigest(), "bounds": bounds}

import itertools
import json
import math

import pytest
from pyproj import Transformer

from app.services.tiles_calibration_geometry import rewrite_tilesets, validate_matrix


def matrix(translation=(0, 0, 0), quarter_turn=False):
    x, y, z = translation
    rotation = [0, 1, 0, 0, -1, 0, 0, 0] if quarter_turn else [1, 0, 0, 0, 0, 1, 0, 0]
    return rotation + [0, 0, 1, 0, x, y, z, 1]


def doc(root):
    return json.dumps({"asset": {"version": "1.0"}, "root": root}).encode()


def transform(m, p):
    return [m[i] * p[0] + m[i + 4] * p[1] + m[i + 8] * p[2] + m[i + 12] for i in range(3)]


def test_translation_and_rotation_are_committed_once_and_local_bounds_remain_unchanged():
    volume = {"box": [0, 0, 0, 3, 0, 0, 0, 4, 0, 0, 0, 5]}
    root_matrix = matrix((4_000_000, 3_000_000, 2_000_000))
    child_matrix = matrix((10, 20, 30))
    child_path = "district/parts/sub.json"
    entry = "district/tileset.json"
    data = {
        entry: doc({"boundingVolume": volume, "transform": root_matrix, "content": {"uri": "./parts/sub.json"}}),
        child_path: doc({"boundingVolume": volume, "transform": child_matrix, "content": {"url": "../chunk.b3dm"}}),
    }
    correction = matrix((7, 8, 9), quarter_turn=True)
    rewritten = rewrite_tilesets(entry, data.__getitem__, correction)
    assert set(rewritten) == {entry}
    root = json.loads(rewritten[entry])["root"]
    point = (1, 2, 3)
    assert transform(root["transform"], transform(child_matrix, point)) == transform(
        correction, transform(root_matrix, transform(child_matrix, point))
    )
    assert root["boundingVolume"] == volume
    assert root["content"]["uri"] == "./parts/sub.json"


def test_geographic_regions_in_all_volume_slots_cover_their_transformed_ecef_points():
    # This region crosses the date line and equator, so endpoints alone would miss extrema.
    region = {"region": [math.radians(v) for v in [179.7, -0.2, -179.8, 0.3]] + [-70, 350]}
    entry = "tileset.json"
    child_path = "some folder/manifest.json"
    root_at = (-6_378_137, 0, 0)
    inner = (12, 20, -7)
    source = {
        entry: doc({"boundingVolume": region, "transform": matrix(root_at),
                    "content": {"uri": "some%20folder/manifest.json", "boundingVolume": region}}),
        child_path: doc({"boundingVolume": region, "viewerRequestVolume": region, "transform": matrix(inner),
                         "contents": [{"uri": "tile.glb", "boundingVolume": region}]}),
    }
    shift = matrix((120, -251, 300), quarter_turn=True)
    rewritten = rewrite_tilesets(entry, source.__getitem__, shift)
    primary = json.loads(rewritten[entry])["root"]
    child = json.loads(rewritten[child_path])["root"]
    assert child["transform"] == matrix(inner)
    assert child["contents"][0]["uri"] == "tile.glb"
    to_ecef = Transformer.from_crs(4979, 4978, always_xy=True)
    for document, slots, site in (
        (primary, [primary["boundingVolume"], primary["content"]["boundingVolume"]], root_at),
        (child, [child["boundingVolume"], child["viewerRequestVolume"], child["contents"][0]["boundingVolume"]],
         tuple(x + y for x, y in zip(root_at, inner))),
    ):
        assert all("region" not in volume for volume in slots)
        for volume in slots:
            center = volume["box"][:3]
            radii = [volume["box"][i] for i in (3, 7, 11)]
            for lon, lat, height in itertools.product(
                [179.7, 179.9, 180, -179.9, -179.8], [-0.2, 0, 0.1, 0.3], [-70, 0, 350]
            ):
                geographic = to_ecef.transform(lon, lat, height)
                local = [coordinate - origin for coordinate, origin in zip(geographic, site)]
                assert all(abs(v - c) <= r for v, c, r in zip(local, center, radii)), document


@pytest.mark.parametrize("bad", [
    matrix()[:15],
    [2, *matrix()[1:]],
    [-1, *matrix()[1:]],
    [True, *matrix()[1:]],
    [*matrix()[:12], float("inf"), *matrix()[13:]],
    [*matrix()[:-1], 0],
])
def test_only_rigid_finite_column_major_matrices_are_accepted(bad):
    assert validate_matrix(matrix((12, 45, -12), True)) == matrix((12, 45, -12), True)
    with pytest.raises(ValueError):
        validate_matrix(bad)


@pytest.mark.parametrize("branch", [
    {"content": {"uri": "../outside.json"}},
    {"content": {"uri": "https://example.net/tileset.json"}},
    {"content": {"uri": "tileset.json"}},
    {"content": {"uri": "missing.json"}},
    {"implicitTiling": {"subdivisionScheme": "QUADTREE"}},
    {"viewerRequestVolume": {"extensions": {"3DTILES_bounding_volume_S2": {"token": "89c1"}}}},
])
def test_a_placement_that_cannot_be_exported_safely_is_rejected(branch):
    source = {"tileset.json": doc({"boundingVolume": {"sphere": [0, 0, 0, 4]}, **branch})}
    with pytest.raises(ValueError):
        rewrite_tilesets("tileset.json", source.__getitem__, matrix((5, 6, 7)))


def test_shared_submanifest_with_conflicting_local_coordinates_is_rejected():
    region = {"region": [1.22, 0.41, 1.23, 0.42, 0, 200]}
    source = {
        "tileset.json": doc({"boundingVolume": region, "children": [
            {"boundingVolume": region, "content": {"uri": "shared.json"}},
            {"boundingVolume": region, "transform": matrix((100, 70, 20)), "content": {"uri": "shared.json"}},
        ]}),
        "shared.json": doc({"boundingVolume": region, "content": {"uri": "model.b3dm"}}),
    }
    with pytest.raises(ValueError, match="共享"):
        rewrite_tilesets("tileset.json", source.__getitem__, matrix((5, 6, 7)))


def test_legacy_multiple_contents_uses_the_content_array():
    region = {"region": [1.22, 0.41, 1.23, 0.42, 0, 200]}
    entry = "tileset.json"
    source = {entry: doc({"boundingVolume": {"sphere": [0, 0, 0, 4]}, "extensions": {
        "3DTILES_multiple_contents": {"content": [{"uri": "model.glb", "boundingVolume": region}]},
    }})}
    rewritten = rewrite_tilesets(entry, source.__getitem__, matrix((5, 6, 7)))
    content = json.loads(rewritten[entry])["root"]["extensions"]["3DTILES_multiple_contents"]["content"][0]
    assert "box" in content["boundingVolume"]

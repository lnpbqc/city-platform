import math

import pytest
from shapely.geometry import Point, shape

from app.spatial import area_m2, clip_geometry, parse_bbox, parse_geometry, representative_coordinates, selection_polygon


def polygon(ring, holes=None):
    return {"type": "Polygon", "coordinates": [ring, *(holes or [])]}


def square(west=0, south=0, east=4, north=4):
    return polygon([[west, south], [east, south], [east, north], [west, north], [west, south]])


def test_bbox_supports_dateline_windows_and_degenerate_point_and_line():
    assert parse_bbox(None) is None
    crossing = parse_bbox("179,-2,-179,2")
    assert crossing.covers(Point(179.5, 0)) and crossing.covers(Point(-179.5, 0))
    assert not crossing.intersects(Point(0, 0))
    assert parse_bbox("1,2,1,2").equals(Point(1, 2))
    assert parse_bbox("1,2,1,4").geom_type == "LineString"
    assert parse_bbox("1,2,3,2").geom_type == "LineString"


@pytest.mark.parametrize("value", ["", "1,2,3", "a,0,1,1", "0,0,nan,1", "0,0,inf,1", "-181,0,1,1", "0,-91,1,1", "0,2,1,1"])
def test_invalid_bbox_reports_chinese_value_error(value):
    with pytest.raises(ValueError, match="bbox"):
        parse_bbox(value)


def test_line_clip_returns_intersection_instead_of_original_geometry():
    geometry = {"type": "LineString", "coordinates": [[-2, 2], [6, 2]]}
    result = clip_geometry(geometry, parse_bbox("0,0,4,4"))
    assert result == {"type": "LineString", "coordinates": [[0.0, 2.0], [4.0, 2.0]]}
    assert geometry["coordinates"] == [[-2, 2], [6, 2]]


def test_selection_holes_and_concavity_have_no_bbox_false_positives():
    hole = [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]
    mask = selection_polygon(polygon(square()["coordinates"][0], [hole]))
    assert clip_geometry({"type": "Point", "coordinates": [2, 2]}, mask) is None
    assert clip_geometry({"type": "Point", "coordinates": [0.5, 0.5]}, mask) is not None
    concave = selection_polygon(polygon([[0, 0], [4, 0], [4, 1], [1, 1], [1, 4], [0, 4], [0, 0]]))
    assert clip_geometry({"type": "Point", "coordinates": [3, 3]}, concave) is None


def test_boundary_touch_returns_lower_dimensional_actual_intersection():
    result = clip_geometry({"type": "LineString", "coordinates": [[-1, -1], [0, 0]]}, parse_bbox("0,0,1,1"))
    assert result == {"type": "Point", "coordinates": [0.0, 0.0]}
    assert clip_geometry(square(), parse_bbox("4,0,5,4")) == {"type": "LineString", "coordinates": [[4.0, 0.0], [4.0, 4.0]]}


def test_multi_geometries_and_3d_positions_remain_json_lists():
    multi = {"type": "MultiLineString", "coordinates": [[[-1, 1, 10], [5, 1, 16]], [[-1, 3, 20], [5, 3, 26]]]}
    result = clip_geometry(multi, parse_bbox("0,0,4,4"))
    assert result == {"type": "MultiLineString", "coordinates": [[[0.0, 1.0, 11.0], [4.0, 1.0, 15.0]], [[0.0, 3.0, 21.0], [4.0, 3.0, 25.0]]]}
    points = {"type": "MultiPoint", "coordinates": [[179.5, 0], [-179.5, 0], [0, 0]]}
    assert len(clip_geometry(points, parse_bbox("179,-1,-179,1"))["coordinates"]) == 2
    polygons = {"type": "MultiPolygon", "coordinates": [square()["coordinates"], square(10, 10, 11, 11)["coordinates"]]}
    clipped = clip_geometry(polygons, parse_bbox("1,1,3,3"))
    assert shape(clipped).equals(shape(square(1, 1, 3, 3)))


@pytest.mark.parametrize("geometry,message", [
    ({"type": "Point", "coordinates": [181, 0]}, "WGS84"),
    ({"type": "Point", "coordinates": [0, 91]}, "WGS84"),
    ({"type": "Point", "coordinates": [0, 0, math.inf]}, "有限"),
    ({"type": "Point", "coordinates": [True, 0]}, "有限"),
    ({"type": "Point", "coordinates": [0]}, "维"),
    ({"type": "Point", "coordinates": [0, 0, 0, 0]}, "维"),
    ({"type": "LineString", "coordinates": [[0, 0], [1, 1, 2]]}, "维"),
    (polygon([[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]]), "拓扑"),
    (polygon([[0, 0], [1, 0], [1, 1], [0, 1]]), "闭合"),
    ({"type": "LineString", "coordinates": [[0, 0]]}, "两个"),
    ({"type": "Feature", "geometry": square()}, "类型"),
])
def test_geometry_validation_rejects_invalid_data_without_repair(geometry, message):
    with pytest.raises(ValueError, match=message):
        parse_geometry(geometry)


@pytest.mark.parametrize("geometry", [None, {"type": "Point", "coordinates": [1, 1]}, {"type": "MultiPolygon", "coordinates": []}, {"type": "Polygon", "coordinates": []}])
def test_selection_requires_nonempty_polygon(geometry):
    with pytest.raises(ValueError, match="Polygon|多边形"):
        selection_polygon(geometry)


def test_missing_empty_and_unmasked_geometry_behaviour():
    assert parse_geometry(None) is None
    assert clip_geometry(None, parse_bbox("0,0,1,1")) is None
    assert parse_geometry({"type": "GeometryCollection", "geometries": []}).is_empty
    assert representative_coordinates({"type": "Polygon", "coordinates": []}) is None
    assert clip_geometry({"type": "Point", "coordinates": [2, 3]}, None) == {"type": "Point", "coordinates": [2.0, 3.0]}


def test_representative_point_is_inside_polygon_and_outside_holes():
    geometry = polygon(square()["coordinates"][0], [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]])
    coordinates = representative_coordinates(geometry)
    assert isinstance(coordinates, list) and len(coordinates) == 2
    assert shape(geometry).contains(Point(*coordinates))


def test_geodesic_area_is_square_metres_and_holes_subtract_regardless_of_winding():
    outer = square(0, 0, 0.02, 0.02)
    hole = square(0.005, 0.005, 0.015, 0.015)["coordinates"][0]
    outer_area = area_m2(outer)
    assert 4_900_000 < outer_area < 4_950_000
    ring = outer["coordinates"][0]
    with_hole = area_m2(polygon(ring, [hole]))
    assert with_hole / outer_area == pytest.approx(0.75, rel=0.0001)
    assert area_m2(polygon(list(reversed(ring)), [list(reversed(hole))])) == pytest.approx(with_hole)


def test_collection_area_only_sums_polygon_parts():
    first, second = square(0, 0, 0.01, 0.01), square(0.02, 0, 0.03, 0.01)
    multi = {"type": "MultiPolygon", "coordinates": [first["coordinates"], second["coordinates"]]}
    collection = {"type": "GeometryCollection", "geometries": [multi, {"type": "Point", "coordinates": [1, 1]}, {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}]}
    assert area_m2(collection) == pytest.approx(area_m2(first) + area_m2(second))
    assert area_m2({"type": "Point", "coordinates": [1, 1]}) is None
    assert area_m2({"type": "LineString", "coordinates": [[0, 0], [1, 1]]}) is None
    assert area_m2(None) is None

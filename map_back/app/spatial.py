"""Strict WGS84 geometry validation, intersection and geodesic measurements."""

import json
import math

from pyproj import Geod
from shapely.errors import ShapelyError
from shapely.geometry import LineString, Point, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.validation import explain_validity

_GEOD = Geod(ellps="WGS84")
_DEPTHS = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}


def parse_bbox(value: str | None) -> BaseGeometry | None:
    if value is None:
        return None
    try:
        coordinates = [float(part.strip()) for part in value.split(",")]
    except (ValueError, AttributeError, OverflowError) as error:
        raise ValueError("bbox 必须是 west,south,east,north 四个有限数字") from error
    if len(coordinates) != 4 or not all(math.isfinite(number) for number in coordinates):
        raise ValueError("bbox 必须包含四个有限数字")
    west, south, east, north = coordinates
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError("bbox 必须位于 WGS84 经纬度范围内，且南界不能大于北界")

    def window(left, right):
        if left == right and south == north:
            return Point(left, south)
        if left == right:
            return LineString([(left, south), (left, north)])
        if south == north:
            return LineString([(left, south), (right, north)])
        return box(left, south, right, north)

    return window(west, east) if west <= east else unary_union([window(west, 180), window(-180, east)])


def _validate_geometry(document):
    if not isinstance(document, dict):
        raise ValueError("几何必须是 GeoJSON 对象")
    if "crs" in document:
        raise ValueError("几何须使用 WGS84 经纬度，不接受旧式 crs 声明")
    kind = document.get("type")
    if kind == "GeometryCollection":
        children = document.get("geometries")
        if not isinstance(children, (list, tuple)):
            raise ValueError("几何集合必须包含 geometries 数组")
        for child in children:
            _validate_geometry(child)
        return
    if not isinstance(kind, str) or kind not in _DEPTHS:
        raise ValueError("不支持的几何类型，请提供点、线、面或几何集合")
    dimensions = set()

    def positions(value, depth):
        if not isinstance(value, (list, tuple)):
            raise ValueError("几何坐标必须是数组")
        if depth:
            for child in value:
                positions(child, depth - 1)
            return
        if not value:
            return
        if len(value) not in (2, 3):
            raise ValueError("位置必须为二维经纬度或三维经纬高")
        try:
            finite = all(isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number) for number in value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("几何坐标必须为有限数字")
        if not (-180 <= value[0] <= 180 and -90 <= value[1] <= 90):
            raise ValueError("几何坐标超出 WGS84 经纬度范围")
        dimensions.add(len(value))

    coordinates = document.get("coordinates")
    positions(coordinates, _DEPTHS[kind])
    if len(dimensions) > 1:
        raise ValueError("同一几何的坐标维数必须一致")
    if kind in ("LineString", "MultiLineString"):
        lines = [coordinates] if kind == "LineString" else coordinates
        for line in lines:
            if line and len(line) < 2:
                raise ValueError("线至少需要两个位置")
    if kind in ("Polygon", "MultiPolygon"):
        polygons = [coordinates] if kind == "Polygon" else coordinates
        for rings in polygons:
            if kind == "MultiPolygon" and not rings:
                raise ValueError("多面几何的成员不能为空")
            for ring in rings:
                if len(ring) < 4 or tuple(ring[0]) != tuple(ring[-1]):
                    raise ValueError("多边形环至少需要四个位置，且首尾必须闭合")


def parse_geometry(document: dict | None) -> BaseGeometry | None:
    if document is None:
        return None
    _validate_geometry(document)
    try:
        geometry = shape(document)
    except (ShapelyError, TypeError, ValueError, IndexError) as error:
        raise ValueError(f"几何结构无效：{error}") from error
    if not geometry.is_valid:
        raise ValueError(f"几何拓扑无效：{explain_validity(geometry)}")
    return geometry


def selection_polygon(document: dict) -> BaseGeometry:
    if not isinstance(document, dict) or document.get("type") != "Polygon":
        raise ValueError("选择范围只接受 GeoJSON Polygon 多边形")
    geometry = parse_geometry(document)
    if geometry.is_empty:
        raise ValueError("选择多边形不能为空")
    return geometry


def clip_geometry(document: dict | None, mask: BaseGeometry | None) -> dict | None:
    geometry = parse_geometry(document)
    if geometry is None:
        return None
    if mask is not None and not isinstance(mask, BaseGeometry):
        raise ValueError("裁剪范围必须是有效几何")
    try:
        result = geometry.intersection(mask) if mask is not None else geometry
        return None if result.is_empty else json.loads(json.dumps(mapping(result), allow_nan=False))
    except (ShapelyError, ValueError, TypeError) as error:
        raise ValueError(f"几何裁剪失败：{error}") from error


def representative_coordinates(document: dict | None) -> list[float] | None:
    geometry = parse_geometry(document)
    if geometry is None or geometry.is_empty:
        return None
    point = geometry.representative_point()
    return [point.x, point.y]


def area_m2(document: dict | None) -> float | None:
    geometry = parse_geometry(document)

    def polygons(value):
        if value is None:
            return
        if value.geom_type == "Polygon":
            yield value
        elif value.geom_type in ("MultiPolygon", "GeometryCollection"):
            for child in value.geoms:
                yield from polygons(child)

    parts = list(polygons(geometry))
    if not parts:
        return 0.0 if geometry is not None and geometry.geom_type == "MultiPolygon" else None
    # Geod uses signed rings; normalize the shell and holes before summation.
    return sum(abs(_GEOD.geometry_area_perimeter(orient(part, sign=1.0))[0]) for part in parts)

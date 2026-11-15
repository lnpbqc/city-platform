"""Bake a rigid ECEF correction into a linked set of 3D Tiles manifests."""

import json
import math
import posixpath
from collections.abc import Callable
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from app.services.asset_metadata import _A, _E2, _IDENTITY

_TILE_FORMATS = {".b3dm", ".glb", ".gltf", ".i3dm", ".pnts", ".cmpt"}
_UNSUPPORTED_EXTENSIONS = {"3DTILES_bounding_volume_S2", "3DTILES_implicit_tiling"}


def _finite_numbers(values, length: int) -> bool:
    if not isinstance(values, list) or len(values) != length:
        return False
    try:
        return all(type(value) in (int, float) and math.isfinite(value) for value in values)
    except OverflowError:
        return False


def _affine(matrix) -> tuple[float, ...]:
    if not _finite_numbers(matrix, 16) or [matrix[index] for index in (3, 7, 11, 15)] != [0, 0, 0, 1]:
        raise ValueError("变换必须是有限的列主序 4×4 仿射矩阵")
    return tuple(map(float, matrix))


def _cross(a, b) -> tuple[float, float, float]:
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def validate_matrix(matrix) -> list[float]:
    values = _affine(matrix)
    a, b, c = (values[index:index + 3] for index in (0, 4, 8))
    # Check norms before dot products, avoiding overflow for out-of-range input.
    if not all(abs(math.hypot(*column) - 1) <= 1e-8 for column in (a, b, c)):
        raise ValueError("校准只支持平移和旋转")
    if (any(abs(math.fsum(x * y for x, y in zip(first, second))) > 1e-8
            for first, second in ((a, b), (a, c), (b, c)))
            or math.dist(_cross(a, b), c) > 1e-8):
        raise ValueError("校准只支持平移和旋转")
    return list(values)


def _multiply(a, b) -> tuple[float, ...]:
    product = tuple(sum(a[row + 4 * i] * b[i + 4 * column] for i in range(4))
                    for column in range(4) for row in range(4))
    if not all(map(math.isfinite, product)):
        raise ValueError("瓦片的累计变换超出数值范围")
    return product


def _inverse_rows(matrix):
    columns = [matrix[index:index + 3] for index in (0, 4, 8)]
    lengths = [math.hypot(*column) for column in columns]
    if min(lengths) <= 0 or not all(map(math.isfinite, lengths)):
        raise ValueError("无法反解瓦片累计变换")
    a, b, c = ([value / length for value in column] for column, length in zip(columns, lengths))
    dual = [_cross(b, c), _cross(c, a), _cross(a, b)]
    determinant = math.fsum(x * y for x, y in zip(a, dual[0]))
    if abs(determinant) < 1e-12:
        raise ValueError("无法反解瓦片累计变换")
    return [[(v / determinant) / length for v in row] for row, length in zip(dual, lengths)]


def _region_box(region, accumulated) -> list[float]:
    if not _finite_numbers(region, 6):
        raise ValueError("瓦片经纬度范围无效")
    west, south, east, north, low, high = region
    if not (-math.pi <= west <= math.pi and -math.pi <= east <= math.pi
            and -math.pi / 2 <= south <= north <= math.pi / 2
            and -_A * (1 - _E2) < low <= high):
        raise ValueError("瓦片经纬度范围无效")
    if east < west:
        east += math.tau

    # At each valid height, geodetic z is monotone in latitude; the horizontal
    # radius can only turn at the equator. Evaluate height endpoints too.
    latitudes = [south, north] + ([0.0] if south < 0 < north else [])
    radial, vertical = [], []
    for lat in latitudes:
        sin_lat, cos_lat = math.sin(lat), math.cos(lat)
        normal = _A / math.sqrt(1 - _E2 * sin_lat ** 2)
        for height in (low, high):
            radial.append((normal + height) * cos_lat)
            vertical.append((normal * (1 - _E2) + height) * sin_lat)
    quadrant = math.pi / 2
    longitudes = [west, east] + [i * quadrant for i in range(math.ceil(west / quadrant), math.floor(east / quadrant) + 1)]
    radius_endpoints = (min(radial), max(radial))
    horizontal = [[r * trig(lon) for r in radius_endpoints for lon in longitudes] for trig in (math.cos, math.sin)]
    axes = [*horizontal, vertical]
    minima, maxima = list(map(min, axes)), list(map(max, axes))
    # Convert the conservative ECEF box back into the original tile coordinate
    # system. Its local axis-aligned enclosure also works with existing shear.
    mid = [lo / 2 + hi / 2 - accumulated[12 + i] for i, (lo, hi) in enumerate(zip(minima, maxima))]
    half = [hi / 2 - lo / 2 + 1e-6 for lo, hi in zip(minima, maxima)]
    rows = _inverse_rows(accumulated)
    center = [math.fsum(weight * point for weight, point in zip(row, mid)) for row in rows]
    radii = [math.fsum(abs(weight) * width for weight, width in zip(row, half)) for row in rows]
    if not all(map(math.isfinite, center + radii)):
        raise ValueError("瓦片包围盒超出数值范围")
    x, y, z = radii
    return [*center, x, 0, 0, 0, y, 0, 0, 0, z]


def _rewrite_volume(volume, accumulated) -> bool:
    if not isinstance(volume, dict) or not isinstance(volume.get("extensions", {}), dict):
        raise ValueError("瓦片包围体无效")
    if _UNSUPPORTED_EXTENSIONS.intersection(volume.get("extensions", {})):
        raise ValueError("暂不支持 S2 或隐式瓦片的包围体")
    shapes = {"box", "sphere", "region"}.intersection(volume)
    if len(shapes) != 1:
        raise ValueError("仅支持盒、球或经纬度范围的瓦片包围体")
    if "region" in volume:
        volume["box"] = _region_box(volume.pop("region"), accumulated)
        return True
    if "box" in volume and not _finite_numbers(volume["box"], 12):
        raise ValueError("瓦片包围盒无效")
    if "sphere" in volume and (not _finite_numbers(volume["sphere"], 4) or volume["sphere"][3] < 0):
        raise ValueError("瓦片包围球无效")
    return False


def _resolve_uri(manifest: str, uri) -> str:
    if not isinstance(uri, str) or not uri or any(ord(char) < 32 for char in uri):
        raise ValueError("瓦片内容引用无效")
    try:
        parts = urlsplit(uri)
        path = unquote(parts.path, errors="strict")
    except ValueError as error:
        raise ValueError("瓦片内容引用无效") from error
    if (parts.scheme or parts.netloc or parts.query or parts.fragment
            or path.startswith("/") or "\\" in path or ":" in path or not path
            or any(ord(char) < 32 for char in path)):
        raise ValueError("只能校准引用包内相对文件的模型")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(manifest), path))
    if resolved in (".", "..") or resolved.startswith("../"):
        raise ValueError("瓦片内容引用超出模型包")
    return resolved


def rewrite_tilesets(entry: str, read: Callable[[str], bytes], matrix: list[float]) -> dict[str, bytes]:
    """Read JSON manifests only. Return package-relative replacements."""
    correction = validate_matrix(matrix)
    if not entry or entry.startswith("/") or "\\" in entry or ":" in entry or any(
        part in ("", ".", "..") for part in entry.split("/")
    ):
        raise ValueError("瓦片清单入口无效")
    outputs: dict[str, bytes | None] = {}
    completed = set()
    ancestors = set()

    def rewrite_tile(tile, parent, manifest: str, primary: bool = False) -> bool:
        if not isinstance(tile, dict) or not isinstance(tile.get("extensions", {}), dict):
            raise ValueError("瓦片定义无效")
        extensions = tile.get("extensions", {})
        if "implicitTiling" in tile or _UNSUPPORTED_EXTENSIONS.intersection(extensions):
            raise ValueError("暂不支持隐式瓦片或 S2 模型校准")
        local = _affine(tile["transform"]) if "transform" in tile else None
        accumulated = _multiply(parent, local) if local else parent
        changed = _rewrite_volume(tile.get("boundingVolume"), accumulated)
        if "viewerRequestVolume" in tile:
            changed |= _rewrite_volume(tile["viewerRequestVolume"], accumulated)
        if primary:
            tile["transform"] = _multiply(correction, accumulated)
            changed = True

        contents = tile.get("contents", [])
        if "3DTILES_multiple_contents" in extensions:
            legacy = extensions["3DTILES_multiple_contents"]
            if not isinstance(legacy, dict) or "contents" in tile or "content" in tile:
                raise ValueError("不支持此多内容瓦片扩展格式")
            contents = legacy.get("contents", legacy.get("content"))
        if not isinstance(contents, list):
            raise ValueError("瓦片内容列表无效")
        if "content" in tile:
            contents = [tile["content"], *contents]
        for content in contents:
            if not isinstance(content, dict) or ("uri" in content and "url" in content):
                raise ValueError("瓦片内容定义无效")
            ref = _resolve_uri(manifest, content.get("uri", content.get("url")))
            if "boundingVolume" in content:
                changed |= _rewrite_volume(content["boundingVolume"], accumulated)
            suffix = PurePosixPath(ref).suffix.lower()
            if suffix == ".json":
                rewrite_manifest(ref, accumulated)
            elif suffix not in _TILE_FORMATS:
                raise ValueError(f"不支持校准引用此文件的瓦片：{ref}")
        children = tile.get("children", [])
        if not isinstance(children, list):
            raise ValueError("子瓦片列表无效")
        for child in children:
            changed |= rewrite_tile(child, accumulated, manifest)
        return changed

    def rewrite_manifest(path: str, parent):
        if path in ancestors:
            raise ValueError(f"瓦片清单存在循环引用：{path}")
        key = (path, parent)
        if key in completed:
            return
        ancestors.add(path)
        try:
            document = json.loads(read(path))
        except (KeyError, OSError, ValueError) as error:
            raise ValueError(f"无法读取瓦片清单：{path}") from error
        if (not isinstance(document, dict) or not isinstance(document.get("asset"), dict)
                or document["asset"].get("version") not in ("1.0", "1.1")):
            raise ValueError(f"不支持此瓦片清单格式：{path}")
        for field in ("extensionsUsed", "extensionsRequired"):
            declared = document.get(field, [])
            if not isinstance(declared, list) or not all(isinstance(name, str) for name in declared):
                raise ValueError(f"瓦片清单扩展列表无效：{path}")
            if _UNSUPPORTED_EXTENSIONS.intersection(declared):
                raise ValueError("暂不支持隐式瓦片或 S2 模型校准")
        changed = rewrite_tile(document.get("root"), parent, path, primary=path == entry)
        output = json.dumps(document, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode() if changed else None
        if path in outputs and outputs[path] != output:
            raise ValueError(f"共享子清单的引用使用不同坐标，无法安全校准：{path}")
        outputs[path] = output
        completed.add(key)
        ancestors.remove(path)

    try:
        rewrite_manifest(entry, tuple(_IDENTITY))
    except RecursionError as error:
        raise ValueError("瓦片清单的嵌套层数过深") from error
    except OverflowError as error:
        raise ValueError("瓦片包围体或变换超出数值范围") from error
    return {path: payload for path, payload in outputs.items() if payload is not None}

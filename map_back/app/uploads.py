import json
import math
import shutil
import stat
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, UploadFile
from .spatial import parse_geometry

GEOJSON_LIMIT = 10 * 1024 * 1024
ZIP_LIMIT = 512 * 1024 * 1024
EXPANDED_LIMIT = 2 * 1024 * 1024 * 1024
FILE_LIMIT = 10_000


def invalid(message: str):
    raise HTTPException(422, message)


async def receive(file: UploadFile, target: Path, limit: int):
    total = 0
    with target.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise HTTPException(413, f"上传文件超过 {limit // 1024 // 1024} MB 上限")
            output.write(chunk)
    if not total:
        invalid("文件为空")


def read_json(path: Path):
    def nonfinite(value):
        invalid(f"JSON包含非有限数值 {value}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=nonfinite)
    except (ValueError, UnicodeError):
        invalid(f"{path.name} 不是有效的 UTF-8 JSON")


def validate_geojson(path: Path):
    data = read_json(path)
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        invalid("GeoJSON 必须为 FeatureCollection")
    if "crs" in data:
        invalid("请移除旧式 crs 声明，并先转换为 WGS84 经纬度")

    def coordinates(value, depth):
        if depth == 0:
            if not isinstance(value, list) or len(value) not in (2, 3):
                invalid("坐标必须包含经度、纬度和可选高度")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
                invalid("坐标必须为有限数字")
            if not (-180 <= value[0] <= 180 and -90 <= value[1] <= 90):
                invalid("坐标超出 WGS84 经纬度范围")
        else:
            if not isinstance(value, list) or not value:
                invalid("几何坐标不能为空")
            for child in value:
                coordinates(child, depth - 1)

    def line(value, ring=False):
        if len(value) < (4 if ring else 2) or (ring and value[0] != value[-1]):
            invalid("线至少需要两个位置；面环至少四个位置且首尾闭合")

    depths = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}
    for feature in data["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            invalid("features 内必须是 Feature")
        if feature.get("properties") is not None and not isinstance(feature["properties"], dict):
            invalid("Feature properties 必须为对象或 null")
        geometry = feature.get("geometry")
        if geometry is None:
            continue
        if not isinstance(geometry, dict) or geometry.get("type") not in depths:
            invalid("仅支持点、线、面及对应多部件几何")
        kind, value = geometry["type"], geometry.get("coordinates")
        coordinates(value, depths[kind])
        if kind == "LineString":
            line(value)
        elif kind == "MultiLineString":
            for part in value:
                line(part)
        elif kind in ("Polygon", "MultiPolygon"):
            for polygon in ([value] if kind == "Polygon" else value):
                for ring in polygon:
                    line(ring, True)
        try:
            parse_geometry(geometry)
        except ValueError as error:
            invalid(str(error))


def extract_tiles(archive: Path, destination: Path):
    try:
        with ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > FILE_LIMIT:
                invalid("ZIP 文件数超过 10,000 上限")
            if sum(item.file_size for item in entries) > EXPANDED_LIMIT:
                raise HTTPException(413, f"ZIP 解压总量超过 {EXPANDED_LIMIT // 1024 // 1024} MiB")
            seen = set()
            for item in entries:
                path = PurePosixPath(item.filename)
                if item.flag_bits & 1:
                    invalid("ZIP 包含加密文件")
                if stat.S_ISLNK(item.external_attr >> 16):
                    invalid("ZIP 包含符号链接")
                if "\\" in item.orig_filename:
                    invalid("ZIP 路径含反斜杠，请使用 / 分隔目录")
                if path.is_absolute() or any(":" in part for part in path.parts):
                    invalid("ZIP 包含绝对路径或驱动器路径")
                if ".." in path.parts:
                    invalid("ZIP 路径包含上级目录 ..")
                if not path.parts:
                    invalid("ZIP 包含空路径")
                key = str(path).casefold()
                if key in seen:
                    invalid("ZIP 包含重复文件路径")
                seen.add(key)
            written = 0
            for item in entries:
                target = destination.joinpath(*PurePosixPath(item.filename).parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > EXPANDED_LIMIT:
                            raise HTTPException(413, f"ZIP 解压总量超过 {EXPANDED_LIMIT // 1024 // 1024} MiB")
                        output.write(chunk)
    except (BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError) as error:
        invalid(f"无法解压 ZIP：{error}")

    entry = destination / "tileset.json"
    if not entry.is_file():
        children = list(destination.iterdir())
        if len(children) == 1 and children[0].is_dir():
            entry = children[0] / "tileset.json"
    if not entry.is_file():
        invalid("ZIP 根目录或唯一顶层文件夹内必须包含 tileset.json")
    manifest = read_json(entry)
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("asset"), dict)
        or manifest["asset"].get("version") not in ("1.0", "1.1")
        or not isinstance(manifest.get("root"), dict) or "boundingVolume" not in manifest["root"]):
        invalid("tileset.json 缺少有效的 asset.version、root 或 boundingVolume")
    return entry


def cleanup(path: Path):
    if path.exists():
        shutil.rmtree(path)

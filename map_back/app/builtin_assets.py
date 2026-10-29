"""Whitelist existing campus samples without copying or relocating their files."""

import json
import stat
from pathlib import Path
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Asset

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = PROJECT_ROOT / "map" / "public" / "samples"
_CAMPUSES = json.loads((PROJECT_ROOT / "map" / "src" / "data" / "campuses.json").read_text(encoding="utf-8"))
CAMPUS_KEYS = tuple(campus["key"] for campus in _CAMPUSES)
CAMPUS_NAMES = {campus["key"]: campus["name"] for campus in _CAMPUSES}
_CAMPUS_SHORT_NAMES = {campus["key"]: campus["shortName"] for campus in _CAMPUSES}

BUILTIN_LAYERS = [
    {"id": "campus-buildings", "name": "校园建筑白模", "type": "geojson", "filename": "campus-buildings.geojson",
     "category": "建筑", "source": "OSM公开轮廓 · 高度含估计 · 非测绘模型", "unit": "m", "color": "#9eafc1", "orderable": False, "map_attached": True},
    {"id": "demo-points", "name": "积水监测点", "type": "geojson", "filename": "water-points.geojson",
     "category": "专题", "source": "合成演示 · 非实测数据", "unit": "cm", "color": "#347af0", "orderable": True, "map_attached": True},
    {"id": "demo-roads", "name": "道路流量", "type": "geojson", "filename": "roads.geojson",
     "category": "道路", "source": "合成演示 · 非真实路网", "unit": "辆/小时", "color": "#e2a23b", "orderable": True, "map_attached": True},
    {"id": "demo-areas", "name": "积水范围", "type": "geojson", "filename": "areas.geojson",
     "category": "专题", "source": "合成演示 · 非风险预测", "unit": "cm", "color": "#36b9ba", "orderable": True, "map_attached": True},
    {"id": "demo-buildings", "name": "三维建筑小样", "type": "3dtiles", "filename": "buildings/tileset.json",
     "category": "建筑", "source": "合成演示 · 非真实建筑", "unit": "m", "color": "#9eafc1", "orderable": False, "map_attached": False},
]


def builtin_asset_id(campus: str, layer_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"city:sample:{campus}:{layer_id}"))


def builtin_asset_for_url(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc:
            if (parsed.scheme not in ("http", "https")
                    or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
                    or parsed.port not in (8000, 5173, 4173)):
                return None
        if not parsed.path.startswith("/samples/"):
            return None
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise HTTPException(422, "默认样例入口不能包含凭据、查询参数或片段")
    except ValueError as error:
        raise HTTPException(422, "默认样例地址格式无效") from error
    for campus in CAMPUS_KEYS:
        for layer in BUILTIN_LAYERS:
            if parsed.path == f"/samples/{campus}/{layer['filename']}":
                return builtin_asset_id(campus, layer["id"])
    raise HTTPException(422, "默认样例地址不在入口白名单")


def builtin_asset_files(identity: str, entry_url: str):
    from .assets import reject_link

    match = next(((campus, layer) for campus in CAMPUS_KEYS for layer in BUILTIN_LAYERS
                  if identity == builtin_asset_id(campus, layer["id"])
                  and entry_url == f"/samples/{campus}/{layer['filename']}"), None)
    if match is None:
        raise ValueError("默认资产标识或入口不在样例白名单")
    campus, layer = match
    for folder in (SAMPLES_DIR.parent, SAMPLES_DIR, SAMPLES_DIR / campus):
        reject_link(folder)
    campus_root = SAMPLES_DIR / campus
    root = campus_root / "buildings" if layer["type"] == "3dtiles" else campus_root
    reject_link(root)
    files = []

    def add(path: Path):
        info = reject_link(path)
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("默认资产文件越界")
        if stat.S_ISDIR(info.st_mode):
            for child in path.iterdir():
                add(child)
        elif stat.S_ISREG(info.st_mode):
            files.append({"path": path.relative_to(root).as_posix(), "size": info.st_size})
        else:
            raise ValueError("默认资产含非常规文件")

    if layer["type"] == "3dtiles":
        for child in root.iterdir():
            add(child)
        entry_relative = "tileset.json"
    else:
        add(root / layer["filename"])
        entry_relative = layer["filename"]
    return root, sorted(files, key=lambda item: item["path"]), entry_relative


def ensure_builtin_assets(session: Session):
    from .assets import ensure_initial_version

    for campus in CAMPUS_KEYS:
        for layer in BUILTIN_LAYERS:
            identity = builtin_asset_id(campus, layer["id"])
            asset = session.get(Asset, identity)
            if asset is None:
                asset = Asset(id=identity, original_name=Path(layer["filename"]).name,
                              name=f"{CAMPUS_NAMES[campus]} · {layer['name']}", type=layer["type"],
                              entry_url=f"/samples/{campus}/{layer['filename']}", source_kind="default", protected=True,
                              source=f"{_CAMPUS_SHORT_NAMES[campus]} · {layer['source']}",
                              coordinate_description="WGS84，经纬度；高程单位：米", byte_size=0, file_count=0,
                              status="active", error="")
                session.add(asset)
                session.flush()
            try:
                _, files, entry = builtin_asset_files(identity, asset.entry_url)
                asset.byte_size = sum(item["size"] for item in files)
                asset.file_count = len(files)
                asset.status, asset.error = ("active", "") if entry in {item["path"] for item in files} else ("missing", "图层入口文件缺失")
                ensure_initial_version(session, asset)
            except FileNotFoundError:
                asset.status, asset.error = "missing", "默认样例文件缺失"
                asset.byte_size, asset.file_count = 0, 0
                ensure_initial_version(session, asset)
            except (OSError, ValueError) as error:
                asset.status, asset.error = "unsafe", str(error)[:1000]
                ensure_initial_version(session, asset)
    session.flush()

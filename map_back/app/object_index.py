"""Version-scoped snapshots; queries never rewrite published geometries."""
import hashlib
import json
import math
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from .assets import lock_catalog, published_files
from .builtin_assets import BUILTIN_LAYERS, CAMPUS_KEYS, builtin_asset_id
from .models import Asset, AssetVersion, ObjectIndex, SpatialObject
from .geojson_stream import members, check_cancel
from .spatial import area_m2, parse_geometry, representative_coordinates


def object_id(asset_id: str, version: str, feature_index: int):
    return str(uuid5(NAMESPACE_URL, f"city:objects:{asset_id}@{version}:{feature_index}"))


def finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:
        return None


def _record(asset, version, ordinal, geometry, properties, kind, name):
    parsed = parse_geometry(geometry)
    envelope = parsed.bounds if parsed is not None and not parsed.is_empty else (None,) * 4
    height = next((number for key in ("height_m", "展示高度_米", "map_extrude_height_m")
                   if (number := finite_number(properties.get(key))) is not None), None)
    confidence = finite_number(properties.get("confidence"))
    if confidence is not None and not 0 <= confidence <= 1:
        confidence = None
    level = properties.get("level", properties.get("等级"))
    level = str(level) if isinstance(level, (str, int, float)) and not isinstance(level, bool) else None
    source = properties.get("semantic_source")
    if not isinstance(source, str) or not source.strip():
        source = ("OSM" if properties.get("数据来源") == "OpenStreetMap" else
                  "synthetic" if properties.get("数据性质") == "合成演示" else
                  "manual" if "人工" in str(properties.get("来源", "")) else
                  "dataset" if properties else "geometry_model")
    return {"id": object_id(asset.id, version.version, ordinal), "asset_id": asset.id, "asset_version": version.version,
            "feature_index": ordinal, "type": kind, "name": name, "height_m": height, "level": level,
            "semantic_source": source, "confidence": confidence, "coordinates": representative_coordinates(geometry),
            "geometry": geometry, "properties": properties, "search_text": json.dumps(properties, ensure_ascii=False, allow_nan=False),
            "area_m2": area_m2(geometry), "west": envelope[0], "south": envelope[1], "east": envelope[2], "north": envelope[3]}


def _records(asset: Asset, version: AssetVersion, cancel=None, *, snapshot=None):
    if asset.type == "3dtiles":
        yield _record(asset, version, -1, None, {}, "model", asset.name or asset.original_name)
        return
    root, files, entry = published_files(asset, version.entry_url)
    if entry not in {item["path"] for item in files}:
        raise ValueError("资产入口文件缺失")
    fingerprint = next((item["sha256"] for item in version.file_manifest or [] if item["path"] == entry), None)
    digest = hashlib.sha256()
    with (root / entry).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check_cancel(cancel)
            digest.update(chunk)
    if fingerprint is None or digest.hexdigest() != fingerprint:
        raise ValueError("入口内容与已发布版本校验和不一致")
    default_kind = next(({"campus-buildings": "building", "demo-roads": "road", "demo-points": "point", "demo-areas": "area"}.get(spec["id"])
                         for campus in CAMPUS_KEYS for spec in BUILTIN_LAYERS if builtin_asset_id(campus, spec["id"]) == asset.id), None)
    ordinal = 0
    for key, feature in members(root / entry, cancel):
        if key is not None:
            if snapshot:
                snapshot.member(key, feature)
            continue
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("索引条目必须是Feature")
        properties = {} if feature.get("properties") is None else feature["properties"]
        if not isinstance(properties, dict):
            raise ValueError("Feature属性必须是对象或null")
        geometry = feature.get("geometry")
        if geometry is not None and not isinstance(geometry, dict):
            raise ValueError("Feature几何必须是对象或null")
        native_kind = properties.get("object_type", properties.get("类型"))
        geometric_kind = {"Point": "point", "MultiPoint": "point", "LineString": "line", "MultiLineString": "line", "Polygon": "area", "MultiPolygon": "area"}.get((geometry or {}).get("type"), "unknown")
        kind = native_kind if isinstance(native_kind, str) and native_kind.strip() else default_kind or geometric_kind
        name = properties.get("name", properties.get("名称"))
        record = _record(asset, version, ordinal, geometry, properties, kind, name if isinstance(name, str) else None)
        if snapshot:
            record.update(snapshot.feature(feature))
        yield record
        ordinal += 1


def index_asset(session: Session, asset: Asset, version: AssetVersion | None = None, *, cancel=None):
    version = version or session.get(AssetVersion, (asset.id, asset.current_version))
    if version is None:
        return None
    existing = session.get(ObjectIndex, (asset.id, version.version))
    if asset.type == "geojson":
        from .geojson_snapshot import ready_snapshot
        if ready_snapshot(session, asset.id, version.version):
            if existing is None:
                existing = ObjectIndex(asset_id=asset.id, asset_version=version.version, status="ready", error="")
                session.add(existing)
            else:
                existing.status, existing.error = "ready", ""
            session.flush()
            return existing
    if existing is not None:
        return existing
    status, error = "unavailable", "该资产类型未提供本地对象索引"
    if asset.source_kind == "external":
        error = "外部资源未读取，无法提供本地对象索引"
    elif asset.type in ("geojson", "3dtiles") and asset.status == "active":
        try:
            with session.begin_nested():
                from .geojson_snapshot import SnapshotWriter
                snapshot = SnapshotWriter(session, asset.id, version.version, cancel) if asset.type == "geojson" else None
                batch = []
                for record in _records(asset, version, cancel, snapshot=snapshot):
                    batch.append(record)
                    if len(batch) == 500:
                        check_cancel(cancel)
                        session.execute(insert(SpatialObject), batch)
                        batch.clear()
                if batch:
                    session.execute(insert(SpatialObject), batch)
                if snapshot:
                    snapshot.complete()
            status, error = "ready", ""
        except (OSError, ValueError, TypeError, KeyError) as cause:
            status, error = "invalid", str(cause)[:1000]
    elif asset.status != "active":
        return None
    state = ObjectIndex(asset_id=asset.id, asset_version=version.version, status=status, error=error)
    session.add(state)
    session.flush()
    return state


def sync_indexes(session: Session):
    lock_catalog(session)
    for asset in session.scalars(select(Asset)):
        for version in session.scalars(select(AssetVersion).where(AssetVersion.asset_id == asset.id)):
            index_asset(session, asset, version)
    session.commit()


def object_counts(session: Session):
    counts = {(asset_id, version): count for asset_id, version, count in session.execute(
        select(SpatialObject.asset_id, SpatialObject.asset_version, func.count()).group_by(SpatialObject.asset_id, SpatialObject.asset_version))}
    return {(state.asset_id, state.asset_version): counts.get((state.asset_id, state.asset_version), 0)
            for state in session.scalars(select(ObjectIndex).join(Asset, Asset.id == ObjectIndex.asset_id)
                                        .where(ObjectIndex.status == "ready", Asset.status == "active"))}

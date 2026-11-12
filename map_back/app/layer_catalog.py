import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .assets import local_parts, lock_catalog, published_files, reconcile
from .builtin_assets import BUILTIN_LAYERS, CAMPUS_KEYS, RETIRED_LAYER_IDS, builtin_asset_id, ensure_builtin_assets
from .contracts import LayerCatalogOutput
from .database import get_session
from .errors import ApiProblem
from .models import Asset, BuiltinLayerState, Layer, ObjectIndex
from .schemas import LayerCatalogStateInput
from .object_index import index_asset, object_counts, sync_indexes

router = APIRouter(prefix="/api/layers/catalog", tags=["layers"])
SessionDep = Annotated[Session, Depends(get_session)]
Campus = Literal["university-town", "huangpu"]
BASEMAP = {"id": "basemap", "name": "底图", "type": "basemap", "category": "底图", "unit": None,
           "color": "#c9dbe8", "orderable": False, "map_attached": True}
DEFAULTS = [BASEMAP, *(spec for spec in BUILTIN_LAYERS if spec["id"] not in RETIRED_LAYER_IDS)]
GROUPS = {"底图", "建筑", "道路", "POI", "水体", "专题", "仿真结果"}


def initialize_catalog(session: Session):
    lock_catalog(session)
    published = set(session.execute(select(Layer.id, Layer.asset_id, Layer.asset_version).join(ObjectIndex,
        (ObjectIndex.asset_id == Layer.asset_id) & (ObjectIndex.asset_version == Layer.asset_version))
        .where(ObjectIndex.status == 'ready')).all())
    ensure_builtin_assets(session)
    ensure_catalog(session)
    result = reconcile(session)
    sync_indexes(session)
    for layer in session.scalars(select(Layer)):
        asset = session.get(Asset, layer.asset_id) if layer.asset_id else None
        index = session.get(ObjectIndex, (layer.asset_id, layer.asset_version)) if layer.asset_id and layer.asset_version else None
        # Both geometry and this flag were published together. Recheck file hashes
        # above, but do not parse an unchanged GiB snapshot on every startup.
        if asset and asset.status == 'active' and index and index.status == 'ready' and (layer.id, layer.asset_id, layer.asset_version) in published:
            continue
        layer.orderable = layer_orderable(session, layer)
    session.commit()
    return result


def layer_orderable(session: Session, layer: Layer):
    if layer.type != "geojson" or not layer.asset_id:
        return False
    asset = session.get(Asset, layer.asset_id)
    if asset is None or asset.source_kind == "external" or asset.status != "active":
        return False
    try:
        from .rendering import expired_source
        if expired_source(session, asset.id, layer.asset_version):
            from .geojson_snapshot import iter_members
            data = (value for key, value in iter_members(session, asset.id, layer.asset_version) if key is None)
        else:
            root, files, entry = published_files(asset)
            parts = local_parts(layer.url)
            entry = parts[1] if parts else entry
            if entry not in {item["path"] for item in files}:
                return False
            from .geojson_stream import features
            data = features(root / entry)
        def has_z(coordinates):
            if not isinstance(coordinates, list):
                return False
            if coordinates and isinstance(coordinates[0], (int, float)):
                return len(coordinates) > 2
            return any(has_z(child) for child in coordinates)

        for feature in data:
            geometry = feature.get("geometry") or {}
            if has_z(geometry.get("coordinates")) or geometry.get("type") == "GeometryCollection":
                return False
            if geometry.get("type") not in ("Polygon", "MultiPolygon"):
                continue
            height = (feature.get("properties") or {}).get("map_extrude_height_m")
            if isinstance(height, (int, float)) and not isinstance(height, bool) and 0 < height <= 1000:
                return False
        return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def ensure_catalog(session: Session):
    if any(session.get(Asset, builtin_asset_id(campus, spec["id"])) is None
           for campus in CAMPUS_KEYS for spec in BUILTIN_LAYERS):
        ensure_builtin_assets(session)
        for campus in CAMPUS_KEYS:
            for spec in BUILTIN_LAYERS:
                index_asset(session, session.get(Asset, builtin_asset_id(campus, spec["id"])))
    for index, spec in enumerate(DEFAULTS):
        if session.get(BuiltinLayerState, spec["id"]) is None:
            session.add(BuiltinLayerState(id=spec["id"], map_attached=spec["map_attached"],
                                         map_visible=True, map_opacity=1, map_order=index))
    session.flush()


def catalog_rows(session: Session, campus: Campus):
    from .timeseries import catalog_timeseries

    result = []
    counts = object_counts(session)
    for spec in DEFAULTS:
        state = session.get(BuiltinLayerState, spec["id"])
        asset = session.get(Asset, builtin_asset_id(campus, spec["id"])) if spec["id"] != "basemap" else None
        result.append({"id": spec["id"], "name": spec["name"], "category": spec["category"], "type": spec["type"],
                       "asset": {"asset_id": asset.id, "version": asset.current_version} if asset else None,
                       "url": asset.entry_url if asset else None, "builtin": True, "campus": campus,
                       "static": True, "orderable": spec["orderable"], "object_count": counts.get((asset.id, asset.current_version)) if asset else 0, "unit": spec["unit"],
                       "legend": [{"label": spec["name"], "color": spec["color"]}], "source": asset.source if asset else "底图服务",
                       "map_attached": state.map_attached, "map_visible": state.map_visible,
                       "map_opacity": state.map_opacity, "road_max_level": state.road_max_level, "order": state.map_order})
    aliases = {"三维建筑": "建筑", "三维模型": "建筑", "线状网络": "道路"}
    for layer in session.scalars(select(Layer)):
        result.append({"id": layer.id, "name": layer.name,
                       "category": aliases.get(layer.category, layer.category),
                       "type": layer.type, "asset": {"asset_id": layer.asset_id, "version": layer.asset_version} if layer.asset_id else None,
                       "url": layer.url, "builtin": False, "campus": None, "source": layer.source,
                       "static": True, "orderable": layer.orderable, "object_count": counts.get((layer.asset_id, layer.asset_version)), "unit": None, "legend": [],
                       "map_attached": layer.map_attached, "map_visible": layer.map_visible,
                       "map_opacity": layer.map_opacity, "road_max_level": layer.road_max_level, "order": layer.map_order})
    from .rendering import describe

    temporal = catalog_timeseries(session)
    for row in result:
        if row["asset"]:
            row.update(temporal.get((row["asset"]["asset_id"], row["asset"]["version"]), {}))
            row["render"] = describe(session, row["asset"]["asset_id"], row["asset"]["version"], row["category"]) if row["static"] else None
    return sorted(result, key=lambda row: (row["order"], row["id"]))


@router.get("", response_model=list[LayerCatalogOutput])
def list_catalog(session: SessionDep, campus: Campus = "university-town"):
    ensure_catalog(session)
    session.commit()
    return catalog_rows(session, campus)


@router.patch("/{layer_id}/map-state", response_model=LayerCatalogOutput)
def update_catalog_state(layer_id: str, body: LayerCatalogStateInput, session: SessionDep, campus: Campus = "university-town"):
    lock_catalog(session)
    ensure_catalog(session)
    states = {state.id: state for state in session.scalars(select(BuiltinLayerState))}
    states.update({layer.id: layer for layer in session.scalars(select(Layer))})
    state = states.get(layer_id)
    if state is None:
        raise ApiProblem(404, "LAYER_NOT_FOUND", "图层不存在")
    rows = catalog_rows(session, campus)
    current = next((row for row in rows if row["id"] == layer_id), None)
    if current is None:
        raise ApiProblem(404, "LAYER_NOT_FOUND", "图层不存在")
    if "order" in body.model_fields_set:
        if not current["orderable"]:
            raise ApiProblem(422, "ORDER_UNSUPPORTED", "顺序调整适用于已核对的二维图层，三维对象按深度遮挡")
        if body.order >= len(rows):
            raise ApiProblem(422, "VALIDATION_ERROR", "顺序超出当前目录范围")
        rows.remove(current)
        rows.insert(body.order, current)
        for index, row in enumerate(rows):
            states[row["id"]].map_order = index
    for key, value in body.model_dump(exclude_unset=True, exclude={"order"}).items():
        setattr(state, key, value)
    session.commit()
    return next(row for row in catalog_rows(session, campus) if row["id"] == layer_id)

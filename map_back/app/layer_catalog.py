import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .assets import local_parts, lock_catalog, published_files, reconcile
from .builtin_assets import BUILTIN_LAYERS, CAMPUS_KEYS, builtin_asset_id, ensure_builtin_assets
from .contracts import LayerCatalogOutput
from .database import get_session
from .errors import ApiProblem
from .models import Asset, BuiltinLayerState, Layer
from .schemas import LayerCatalogStateInput
from .object_index import index_asset, object_counts, sync_indexes

router = APIRouter(prefix="/api/layers/catalog", tags=["layers"])
SessionDep = Annotated[Session, Depends(get_session)]
Campus = Literal["university-town", "huangpu"]
BASEMAP = {"id": "basemap", "name": "底图", "type": "basemap", "category": "底图", "unit": None,
           "color": "#c9dbe8", "orderable": False, "map_attached": True}
DEFAULTS = [BASEMAP, *BUILTIN_LAYERS]
GROUPS = {"底图", "建筑", "道路", "水体", "专题", "仿真结果"}


def initialize_catalog(session: Session):
    lock_catalog(session)
    ensure_builtin_assets(session)
    ensure_catalog(session)
    result = reconcile(session)
    sync_indexes(session)
    for layer in session.scalars(select(Layer)):
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
        root, files, entry = published_files(asset)
        parts = local_parts(layer.url)
        entry = parts[1] if parts else entry
        if entry not in {item["path"] for item in files}:
            return False
        data = json.loads((root / entry).read_text(encoding="utf-8-sig"))
        def has_z(coordinates):
            if not isinstance(coordinates, list):
                return False
            if coordinates and isinstance(coordinates[0], (int, float)):
                return len(coordinates) > 2
            return any(has_z(child) for child in coordinates)

        for feature in data.get("features", []):
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
                       "map_opacity": state.map_opacity, "order": state.map_order})
    aliases = {"三维建筑": "建筑", "三维模型": "建筑", "线状网络": "道路"}
    for layer in session.scalars(select(Layer)):
        result.append({"id": layer.id, "name": layer.name,
                       "category": layer.category if layer.category in GROUPS else aliases.get(layer.category, "专题"),
                       "type": layer.type, "asset": {"asset_id": layer.asset_id, "version": layer.asset_version} if layer.asset_id else None,
                       "url": layer.url, "builtin": False, "campus": None, "source": layer.source,
                       "static": True, "orderable": layer.orderable, "object_count": counts.get((layer.asset_id, layer.asset_version)), "unit": None, "legend": [],
                       "map_attached": layer.map_attached, "map_visible": layer.map_visible,
                       "map_opacity": layer.map_opacity, "order": layer.map_order})
    temporal = catalog_timeseries(session)
    for row in result:
        if row["asset"]:
            row.update(temporal.get((row["asset"]["asset_id"], row["asset"]["version"]), {}))
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
    current = next(row for row in rows if row["id"] == layer_id)
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

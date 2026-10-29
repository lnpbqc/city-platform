from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import and_, false, or_, select, text
from sqlalchemy.orm import Session

from .builtin_assets import BUILTIN_LAYERS, CAMPUS_KEYS, builtin_asset_id
from .contracts import Geometry, ObjectOutput, ObjectSummary, Page
from .database import get_session
from .errors import ApiProblem
from .models import Asset, AssetVersion, Layer, ObjectIndex, Scene, SceneAssetReference, SpatialObject
from .spatial import area_m2, clip_geometry, parse_bbox, representative_coordinates, selection_polygon

router = APIRouter(prefix="/api/objects", tags=["objects"])


def get_query_session(session: Annotated[Session, Depends(get_session)]):
    # sqlite3 legacy transactions do not start on SELECT; keep count/page/detail
    # in one read snapshot when another request deletes an unreferenced asset.
    if session.bind.dialect.name == "sqlite" and not session.in_transaction():
        session.execute(text("BEGIN"))
    return session


SessionDep = Annotated[Session, Depends(get_query_session)]


class ObjectFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str | None = Field(default=None, max_length=80)
    version: str | None = Field(default=None, max_length=32)
    layer_id: str | None = Field(default=None, max_length=80)
    type: str | None = Field(default=None, max_length=500)
    q: str | None = Field(default=None, max_length=500)
    bbox: str | None = None
    time: AwareDatetime | None = None
    resolution: Literal["hour", "day"] = "hour"
    campus: Literal["university-town", "huangpu"] = "university-town"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ObjectSelectionInput(ObjectFilters):
    geometry: Geometry


def _available(session: Session, asset: Asset, version: str):
    if session.get(AssetVersion, (asset.id, version)) is None:
        raise ApiProblem(404, "ASSET_VERSION_NOT_FOUND", "资产版本不存在")
    if asset.status != "active":
        raise ApiProblem(409, "ASSET_UNAVAILABLE", "资产不可用", {"status": asset.status, "reason": asset.error})
    state = session.get(ObjectIndex, (asset.id, version))
    if state is None or state.status != "ready":
        raise ApiProblem(409, "OBJECT_INDEX_UNAVAILABLE", state.error if state else "该资产尚未建立本地对象索引")


def scene_layer_reference(session: Session, query: ObjectFilters):
    if not query.asset_id or not query.version:
        return False
    reference = {"asset_id": query.asset_id, "version": query.version}
    documents = session.scalars(select(Scene.document).join(SceneAssetReference, SceneAssetReference.scene_id == Scene.id)
        .where(SceneAssetReference.asset_id == query.asset_id, SceneAssetReference.asset_version == query.version))
    return any(layer["layer_id"] == query.layer_id and layer["asset"] == reference
               for document in documents for layer in document["layers"])


def layer_reference(session: Session, query: ObjectFilters):
    identity, version = query.asset_id, query.version
    if query.layer_id:
        layer = session.get(Layer, query.layer_id)
        if layer:
            if (not layer.asset_id or identity and identity != layer.asset_id or version and version != layer.asset_version) and scene_layer_reference(session, query):
                return identity, version
            if not layer.asset_id:
                raise ApiProblem(409, "OBJECT_INDEX_UNAVAILABLE", "该图层没有本地对象索引")
            if identity and identity != layer.asset_id or version and version != layer.asset_version:
                raise ApiProblem(422, "VALIDATION_ERROR", "资产版本与图层绑定不一致")
            identity, version = layer.asset_id, layer.asset_version
        elif query.layer_id == "basemap":
            return None, None
        elif query.layer_id in {spec["id"] for spec in BUILTIN_LAYERS}:
            allowed = {builtin_asset_id(campus, query.layer_id) for campus in CAMPUS_KEYS}
            if identity and identity not in allowed:
                raise ApiProblem(422, "VALIDATION_ERROR", "资产与默认图层不一致")
            identity = identity or builtin_asset_id(query.campus, query.layer_id)
        else:
            if scene_layer_reference(session, query):
                return identity, version
            raise ApiProblem(404, "LAYER_NOT_FOUND", "图层不存在")
    return identity, version


def _conditions(session: Session, query: ObjectFilters):
    identity, version = layer_reference(session, query)
    if query.layer_id == "basemap" and identity is None:
        return [false()]
    filters = [Asset.status == "active", ObjectIndex.status == "ready"]
    if identity:
        asset = session.get(Asset, identity)
        if asset is None:
            raise ApiProblem(404, "ASSET_NOT_FOUND", "资产不存在")
        version = version or asset.current_version
        _available(session, asset, version)
        filters.extend([SpatialObject.asset_id == identity, SpatialObject.asset_version == version])
    elif version:
        filters.append(SpatialObject.asset_version == version)
    else:
        filters.append(SpatialObject.asset_version == Asset.current_version)
    if query.type:
        filters.append(SpatialObject.type == query.type)
    if query.q and query.q.strip():
        filters.append(or_(*(column.icontains(query.q.strip(), autoescape=True)
                            for column in (SpatialObject.id, SpatialObject.name, SpatialObject.search_text))))
    return filters


def _statement(*columns):
    return select(*columns).select_from(SpatialObject).join(Asset, Asset.id == SpatialObject.asset_id).join(
        ObjectIndex, and_(ObjectIndex.asset_id == SpatialObject.asset_id, ObjectIndex.asset_version == SpatialObject.asset_version))


@dataclass
class Selection:
    ids: list[str]
    clipped: dict[str, dict]


def select_objects(session: Session, query: ObjectFilters, polygon: dict | None = None):
    try:
        mask = parse_bbox(query.bbox)
        if polygon is not None:
            polygon_mask = selection_polygon(polygon)
            mask = mask.intersection(polygon_mask) if mask is not None else polygon_mask
    except ValueError as error:
        raise ApiProblem(422, "VALIDATION_ERROR", str(error)) from error
    filters = _conditions(session, query)
    if mask is None:
        return Selection(list(session.scalars(_statement(SpatialObject.id).where(*filters).order_by(SpatialObject.id))), {})
    if mask.is_empty:
        return Selection([], {})
    parts = list(mask.geoms) if hasattr(mask, "geoms") else [mask]
    windows = [part.bounds for part in parts if not part.is_empty]
    overlaps = [and_(SpatialObject.west <= east, SpatialObject.east >= west,
                     SpatialObject.south <= north, SpatialObject.north >= south) for west, south, east, north in windows]
    candidates = session.execute(_statement(SpatialObject.id, SpatialObject.west, SpatialObject.south, SpatialObject.east, SpatialObject.north)
                                 .where(*filters, or_(*overlaps)).order_by(SpatialObject.id)).all()
    selected, boundary = set(), []
    for row in candidates:
        if polygon is None and any(west <= row.west and south <= row.south and east >= row.east and north >= row.north
                                   for west, south, east, north in windows):
            selected.add(row.id)
        else:
            boundary.append(row.id)
    clipped = {}
    if boundary:
        for identity, geometry in session.execute(select(SpatialObject.id, SpatialObject.geometry).where(SpatialObject.id.in_(boundary))):
            result = clip_geometry(geometry, mask)
            if result is not None:
                selected.add(identity)
                clipped[identity] = result
    return Selection([row.id for row in candidates if row.id in selected], clipped)


def _layer_refs(session: Session):
    result = {(builtin_asset_id(campus, spec["id"]), "1.0.0"): spec["id"] for campus in CAMPUS_KEYS for spec in BUILTIN_LAYERS}
    for layer in session.scalars(select(Layer).where(Layer.asset_id.is_not(None)).order_by(Layer.created_at, Layer.id)):
        result.setdefault((layer.asset_id, layer.asset_version), layer.id)
    return result


def _output(row: SpatialObject, layer_refs, clipped=None, preferred_layer=None):
    geometry = row.geometry if clipped is None else clipped
    return {"object_id": row.id, "asset": {"asset_id": row.asset_id, "version": row.asset_version},
            "layer_id": preferred_layer or layer_refs.get((row.asset_id, row.asset_version)), "type": row.type,
            "name": row.name, "height_m": row.height_m, "level": row.level, "semantic_source": row.semantic_source,
            "confidence": row.confidence, "geometry": geometry, "properties": row.properties,
            "coordinates": row.coordinates if clipped is None else representative_coordinates(clipped),
            "feature_index": row.feature_index if row.feature_index >= 0 else None}


def _page(session, query, selection):
    start = (query.page - 1) * query.page_size
    ids = selection.ids[start:start + query.page_size]
    rows = {row.id: row for row in session.scalars(select(SpatialObject).where(SpatialObject.id.in_(ids)))} if ids else {}
    refs = _layer_refs(session) if ids else {}
    items = [_output(rows[identity], refs, selection.clipped.get(identity), query.layer_id) for identity in ids]
    if query.time is not None:
        from .timeseries import attach_temporal
        attach_temporal(session, items, query.time, query.resolution)
    return {"items": items,
            "total": len(selection.ids), "page": query.page, "page_size": query.page_size}


@router.get("", response_model=Page[ObjectOutput])
def list_objects(query: Annotated[ObjectFilters, Query()], session: SessionDep):
    return _page(session, query, select_objects(session, query))


@router.post("/select", response_model=Page[ObjectOutput])
def select_polygon(body: ObjectSelectionInput, session: SessionDep):
    query = ObjectFilters.model_validate(body.model_dump(exclude={"geometry"}))
    return _page(session, query, select_objects(session, query, body.geometry.model_dump(exclude_none=True)))


@router.get("/summary", response_model=ObjectSummary)
def summarize_objects(query: Annotated[ObjectFilters, Query()], session: SessionDep):
    selection = select_objects(session, query)
    groups = {}
    if selection.ids:
        for row in session.execute(select(SpatialObject.id, SpatialObject.type, SpatialObject.area_m2, SpatialObject.height_m).where(SpatialObject.id.in_(selection.ids))):
            group = groups.setdefault(row.type, {"type": row.type, "count": 0, "area_m2": None, "min_height_m": None, "max_height_m": None})
            group["count"] += 1
            area = row.area_m2
            if area is not None and row.id in selection.clipped:
                area = area_m2(selection.clipped[row.id]) or 0.0
            if area is not None:
                group["area_m2"] = (group["area_m2"] or 0) + area
            if row.height_m is not None:
                group["min_height_m"] = min(group["min_height_m"], row.height_m) if group["min_height_m"] is not None else row.height_m
                group["max_height_m"] = max(group["max_height_m"], row.height_m) if group["max_height_m"] is not None else row.height_m
    return {"total": len(selection.ids), "types": [groups[key] for key in sorted(groups)]}


@router.get("/{identity}", response_model=ObjectOutput)
def get_object(identity: str, session: SessionDep, time: AwareDatetime | None = None,
               resolution: Literal["hour", "day"] = "hour"):
    row = session.get(SpatialObject, identity)
    if row is None:
        raise ApiProblem(404, "OBJECT_NOT_FOUND", "对象不存在")
    _available(session, session.get(Asset, row.asset_id), row.asset_version)
    result = _output(row, _layer_refs(session))
    if time is not None:
        from .timeseries import attach_temporal
        attach_temporal(session, [result], time, resolution)
    return result

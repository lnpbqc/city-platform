"""Read immutable, version-bound synthetic observations without changing assets."""
import math
from datetime import datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .builtin_assets import BUILTIN_LAYERS, CAMPUS_KEYS, builtin_asset_id
from .contracts import LayerTimesOutput, TimeSeriesOutput
from .errors import ApiProblem
from .models import Asset, AssetVersion, Layer, ObjectIndex, SpatialObject, TimeSeriesSnapshot
from .object_queries import ObjectFilters, SessionDep, layer_reference, select_objects

router = APIRouter(tags=["timeseries"])
SHANGHAI = ZoneInfo("Asia/Shanghai")
Resolution = Literal["hour", "day"]
SAMPLE_TIMES = tuple(datetime(2026, 10, day, hour, tzinfo=SHANGHAI).astimezone(timezone.utc)
                     for day in (25, 26) for hour in (8, 9))
SAMPLE_VALUES = {
    "demo-points": [(0, 10, 20, 30), (None, 12, 22, 32), (5, 15, None, None)],
    "demo-roads": [(0, 100, 200, 300), (None, 120, None, None)],
    "demo-areas": [(0, 10, None, None)],
}


class LayerTimeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str | None = Field(default=None, max_length=80)
    version: str | None = Field(default=None, max_length=32)
    campus: Literal["university-town", "huangpu"] = "university-town"


class TimeSeriesQuery(LayerTimeQuery):
    layer_id: str = Field(min_length=1, max_length=80)
    time: AwareDatetime
    resolution: Resolution = "hour"
    bbox: str | None = None


def utc_text(value: datetime):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalized_time(value: datetime, resolution: Resolution):
    try:
        if value.utcoffset() is None:
            raise ValueError("时间必须带时区")
        if resolution == "day":
            value = value.astimezone(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0)
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError) as cause:
        raise ApiProblem(422, "VALIDATION_ERROR", "时间超出可转换的时区范围") from cause


def safe_average(values: list[float]):
    if not values:
        return None
    try:
        return math.fsum(values) / len(values)
    except OverflowError:
        scale = max(abs(value) for value in values)
        return math.fsum(value / scale for value in values) / len(values) * scale


def values_at(snapshot: TimeSeriesSnapshot, time: datetime, resolution: Resolution):
    normalized = normalized_time(time, resolution)
    if resolution == "hour":
        return normalized, snapshot.document.get(utc_text(normalized), {})
    local_day = normalized.astimezone(SHANGHAI).date()
    grouped = {}
    for stamp, values in snapshot.document.items():
        if datetime.fromisoformat(stamp).astimezone(SHANGHAI).date() != local_day:
            continue
        for identity, value in values.items():
            if value is not None:
                grouped.setdefault(identity, []).append(value)
    return normalized, {identity: safe_average(values) for identity, values in grouped.items()}


def ensure_timeseries(session: Session):
    from .assets import lock_catalog

    lock_catalog(session)
    units = {spec["id"]: spec["unit"] for spec in BUILTIN_LAYERS}
    for campus in CAMPUS_KEYS:
        for layer_id, patterns in SAMPLE_VALUES.items():
            identity, version = builtin_asset_id(campus, layer_id), "1.0.0"
            if session.get(TimeSeriesSnapshot, (identity, version)) is not None:
                continue
            asset = session.get(Asset, identity)
            state = session.get(ObjectIndex, (identity, version))
            if asset is None or asset.status != "active" or state is None or state.status != "ready":
                continue
            objects = list(session.scalars(select(SpatialObject).where(
                SpatialObject.asset_id == identity, SpatialObject.asset_version == version).order_by(SpatialObject.feature_index)))
            if not objects:
                continue
            document = {utc_text(time): {row.id: patterns[row.feature_index][position]
                        for row in objects if 0 <= row.feature_index < len(patterns)}
                        for position, time in enumerate(SAMPLE_TIMES)}
            session.add(TimeSeriesSnapshot(asset_id=identity, asset_version=version, unit=units[layer_id], document=document))
    session.flush()


def series_for_layer(session: Session, layer_id: str, query: LayerTimeQuery):
    layer = session.get(Layer, layer_id)
    if layer is not None and not layer.asset_id and not (query.asset_id and query.version):
        return None, None
    identity, version = layer_reference(session, ObjectFilters(layer_id=layer_id, **query.model_dump()))
    if identity is None:
        return None, None
    asset = session.get(Asset, identity)
    if asset is None:
        raise ApiProblem(404, "ASSET_NOT_FOUND", "资产不存在")
    version = version or asset.current_version
    if session.get(AssetVersion, (identity, version)) is None:
        raise ApiProblem(404, "ASSET_VERSION_NOT_FOUND", "资产版本不存在")
    if asset.status != "active":
        raise ApiProblem(409, "ASSET_UNAVAILABLE", "资产不可用", {"status": asset.status, "reason": asset.error})
    return {"asset_id": identity, "version": version}, session.get(TimeSeriesSnapshot, (identity, version))


def attach_temporal(session: Session, items: list[dict], time: datetime, resolution: Resolution):
    normalized = normalized_time(time, resolution)
    snapshots = {}
    for item in items:
        key = (item["asset"]["asset_id"], item["asset"]["version"])
        if key not in snapshots:
            series = session.get(TimeSeriesSnapshot, key)
            if series is not None and not series.document:
                series = None
            snapshots[key] = (series, values_at(series, time, resolution)[1] if series else {})
        series, values = snapshots[key]
        value = values.get(item["object_id"])
        item["temporal"] = {"time": normalized, "resolution": resolution, "unit": series.unit,
                            "value": value, "missing": value is None} if series else None


def catalog_timeseries(session: Session):
    result = {}
    for snapshot in session.scalars(select(TimeSeriesSnapshot)):
        if not snapshot.document:
            continue
        numbers = [value for values in snapshot.document.values() for value in values.values() if value is not None]
        low, high = (100, 300) if snapshot.unit == "辆/小时" else (10, 30)
        bins = [("0", "#dbeafe", lambda value: value == 0),
                (f"0–{low}", "#93c5fd", lambda value: 0 < value <= low),
                (f"{low}–{high}", "#3b82f6", lambda value: low < value <= high),
                (f">{high}", "#1d4ed8", lambda value: value > high)]
        legend = []
        for label, color, includes in bins:
            observed = [value for value in numbers if includes(value)]
            actual = f"{min(observed):g}–{max(observed):g}" if observed else None
            legend.append({"label": f"{label} {snapshot.unit}", "color": color, "value": actual})
        legend.append({"label": "缺测", "color": "#94a3b8", "value": None})
        result[(snapshot.asset_id, snapshot.asset_version)] = {"static": False, "unit": snapshot.unit, "legend": legend}
    return result


@router.get("/api/layers/{layer_id}/times", response_model=LayerTimesOutput)
def layer_times(layer_id: str, query: Annotated[LayerTimeQuery, Query()], session: SessionDep):
    _, snapshot = series_for_layer(session, layer_id, query)
    return sorted(datetime.fromisoformat(stamp).astimezone(timezone.utc) for stamp in snapshot.document) if snapshot else []


@router.get("/api/timeseries", response_model=TimeSeriesOutput)
def get_timeseries(query: Annotated[TimeSeriesQuery, Query()], session: SessionDep):
    reference_query = LayerTimeQuery.model_validate(query.model_dump(include={"asset_id", "version", "campus"}))
    reference, snapshot = series_for_layer(session, query.layer_id, reference_query)
    if snapshot is None or not snapshot.document:
        raise ApiProblem(409, "TIMESERIES_UNAVAILABLE", "该资产版本没有可用时序数据")
    selection = select_objects(session, ObjectFilters(layer_id=query.layer_id, **query.model_dump(exclude={"layer_id"})))
    rows = {row.id: row for row in session.scalars(select(SpatialObject).where(SpatialObject.id.in_(selection.ids)))} if selection.ids else {}
    time, values = values_at(snapshot, query.time, query.resolution)
    items = []
    for identity in selection.ids:
        value = values.get(identity)
        items.append({"object_id": identity, "value": value, "missing": value is None,
                      "geometry": selection.clipped.get(identity, rows[identity].geometry) if value is not None else None})
    return {"layer_id": query.layer_id, "asset": reference, "time": time, "resolution": query.resolution,
            "unit": snapshot.unit, "items": items}

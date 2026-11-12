"""Write a POI edit into a new snapshot without downloading or buffering the layer."""
import json
from tempfile import TemporaryFile
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from fastapi import HTTPException
from sqlalchemy.orm import Session
from .geojson_snapshot import ensure_snapshot, iter_members
from .models import Layer, Asset, SpatialObject
from .errors import ApiProblem


class PoiChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    asset_id: str = Field(min_length=1, max_length=36)
    version: str = Field(min_length=1, max_length=32)
    operation: Literal['add', 'update', 'delete']
    object_id: str | None = None
    feature: dict | None = None


def rewrite(session: Session, layer_id: str, change: PoiChange, target: Path):
    layer = session.get(Layer, layer_id)
    if layer is None:
        raise HTTPException(404, '图层登记不存在')
    if (layer.asset_id, layer.asset_version) != (change.asset_id, change.version):
        raise ApiProblem(409, 'POI_SNAPSHOT_CONFLICT', 'POI 图层已更新，请重新加载后编辑')
    asset = session.get(Asset, change.asset_id)
    if layer.category != 'POI' or layer.type != 'geojson' or not asset or asset.source_kind != 'upload' or asset.protected or asset.status != 'active':
        raise HTTPException(422, '只能编辑本地上传的 POI 图层')
    index = None
    original_geometry = None
    if change.operation != 'add':
        item = session.get(SpatialObject, change.object_id)
        if item is None or (item.asset_id, item.asset_version) != (change.asset_id, change.version):
            raise HTTPException(422, '原点位已不可用，请重新选择')
        index = item.feature_index
        original_geometry = item.geometry
    if change.operation != 'delete':
        feature = change.feature
        if not feature or feature.get('type') != 'Feature' or (feature.get('geometry') or {}).get('type') != 'Point':
            raise HTTPException(422, 'POI 图层只接受 WGS84 Point 要素')
    geometry_changed = change.operation != 'update' or (
        (original_geometry or {}).get('coordinates') != change.feature['geometry'].get('coordinates'))
    if not ensure_snapshot(session, change.asset_id, change.version):
        raise HTTPException(422, '完整 GeoJSON 快照尚未就绪')
    encode = lambda value: json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    count, found = 0, False
    with target.open('w', encoding='utf8') as output, TemporaryFile(mode="w+", encoding="utf8") as extras:
        output.write('{"type":"FeatureCollection","features":[')
        ordinal = 0
        for key, value in iter_members(session, change.asset_id, change.version):
            if key is not None:
                if key != 'type' and (key != 'bbox' or not geometry_changed):
                    extras.write(',' + encode(key) + ':' + encode(value))
                continue
            if ordinal == index:
                found = True
                if change.operation == 'delete':
                    ordinal += 1
                    continue
                properties = {**(value.get('properties') or {}), **(change.feature.get('properties') or {})}
                geometry = {**(value.get('geometry') or {}), **change.feature['geometry']}
                value = {**value, **change.feature, 'properties': properties, 'geometry': geometry}
                if geometry_changed:
                    value.pop('bbox', None)
                    value['geometry'].pop('bbox', None)
            if count:
                output.write(',')
            output.write(encode(value))
            count += 1
            ordinal += 1
        if index is not None and not found:
            raise HTTPException(422, '原点位已不可用，请重新选择')
        if change.operation == 'add':
            if count:
                output.write(',')
            output.write(encode(change.feature))
        output.write(']')
        extras.seek(0)
        while chunk := extras.read(1024 * 1024):
            output.write(chunk)
        output.write('}')

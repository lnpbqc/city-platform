"""Version-bound, bounded map display and geodesic nearby POI queries."""
import json
import math
from collections import Counter
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pyproj import Geod, CRS, Transformer
from shapely.geometry import mapping, shape, Point, MultiLineString
from shapely import transform, line_merge, prepare
from sqlalchemy import case, func, select
from sqlalchemy.orm import load_only

from .errors import ApiProblem
from .models import Asset, SpatialObject
from .object_queries import ObjectFilters, SessionDep, _available, _conditions, referenced_layer_category
from .spatial import parse_bbox
from .spatial_index import candidates
from .road_style import RANK, road_rank, classification, road_groups, signature

router = APIRouter(prefix='/api/map', tags=['map'])
MAX_FEATURES = 2000
MAX_VERTICES = 100_000
MAX_BYTES = 10 * 1024 * 1024
GEOD = Geod(ellps='WGS84')


class LayerReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    layer_id: str = Field(min_length=1, max_length=80)
    asset_id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=32)
    campus: Literal['university-town', 'huangpu'] = 'university-town'


class ViewportInput(LayerReference):
    bbox: list[float] = Field(min_length=4, max_length=4)
    width: int = Field(ge=1, le=16384)
    height: int = Field(ge=1, le=16384)
    road_max_level: int = Field(default=2, ge=1, le=4, strict=True)
    meters_per_pixel: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def valid_bbox(self):
        parse_bbox(','.join(map(str, self.bbox)))
        return self


class NearbyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    layers: list[LayerReference] = Field(max_length=100)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    radius_m: float = Field(default=1000, gt=0, le=1000, allow_inf_nan=False)
    limit: int = Field(default=20, ge=1, le=20)


def validate_reference(session, reference):
    query = ObjectFilters(**reference.model_dump(include=set(LayerReference.model_fields)))
    _conditions(session, query)
    return referenced_layer_category(session, query)


def bbox_windows(bbox):
    west, south, east, north = bbox
    return [(west, south, east, north)] if west <= east else [(west, south, 180, north), (-180, south, east, north)]


def vertices(geometry):
    if geometry.get('type') == 'GeometryCollection':
        return sum(vertices(child) for child in geometry.get('geometries', []))
    def count(value):
        if not value:
            return 0
        if isinstance(value[0], (float, int)):
            return 1
        return sum(count(child) for child in value)
    return count(geometry.get('coordinates', []))


def lightweight(session, identities):
    # SQL projection avoids reading a potentially enormous line or polygon for a card.
    columns = [getattr(SpatialObject, name) for name in ('id', 'asset_id', 'asset_version', 'feature_index', 'type',
               'name', 'height_m', 'level', 'semantic_source', 'confidence', 'coordinates', 'properties')]
    point_geometry = case((func.json_extract(SpatialObject.geometry, '$.type') == 'Point', SpatialObject.geometry), else_=None)
    rows = session.execute(select(*columns, point_geometry.label('point_geometry'))
                           .where(SpatialObject.id.in_(identities))).mappings()
    result = {}
    for row in rows:
        record = dict(row)
        record['geometry'] = record.pop('point_geometry')
        result[row['id']] = record
    return result


def light_output(record, layer_id=None):
    return {'object_id': record['id'], 'asset': {'asset_id': record['asset_id'], 'version': record['asset_version']},
            'layer_id': layer_id, 'type': record['type'], 'name': record['name'], 'height_m': record['height_m'],
            'level': record['level'], 'semantic_source': record['semantic_source'], 'confidence': record['confidence'],
            'coordinates': record['coordinates'], 'geometry': record['geometry'], 'properties': record['properties'],
            'feature_index': record['feature_index'] if record['feature_index'] >= 0 else None}


class RoadPickInput(LayerReference):
    object_ids: list[str] = Field(default_factory=list, max_length=2000)
    display_group_id: str | None = Field(default=None, min_length=1, max_length=200)
    render_key: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)

    @model_validator(mode='after')
    def pick_source(self):
        if self.object_ids:
            if self.display_group_id is not None or self.render_key is not None:
                raise ValueError('来源路段与显示道路组须二选一')
        elif self.display_group_id is None or self.render_key is None:
            raise ValueError('需要来源路段或显示道路组及切片版本')
        return self


class RoadGroupsInput(LayerReference):
    render_key: str = Field(pattern=r'^[a-f0-9]{64}$')
    object_ids: list[str] = Field(min_length=1, max_length=2000)


@router.post('/road-groups')
def selected_road_groups(body: RoadGroupsInput, session: SessionDep):
    from .render_models import RenderJob
    from .rendering import RENDER_DIR
    validate_reference(session, body)
    job = session.get(RenderJob, body.render_key)
    if not job or job.status != 'succeeded' or (job.asset_id, job.version) != (body.asset_id, body.version):
        raise ApiProblem(422, 'VALIDATION_ERROR', '显示产物不属于当前资产版本')
    remaining, groups = set(body.object_ids), []
    try:
        with (RENDER_DIR / job.key / 'road_sources.jsonl').open(encoding='utf8') as source:
            for line in source:
                row = json.loads(line)
                matches = remaining.intersection(row['source_object_ids'])
                if matches:
                    groups.append({'group_id': row['group_id'], 'object_ids': sorted(matches)})
                    remaining.difference_update(matches)
                if not remaining:
                    break
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ApiProblem(409, 'RENDER_UNAVAILABLE', '显示道路来源映射不可用') from error
    return {'groups': groups}


def meters_per_pixel(body):
    if body.meters_per_pixel is not None:
        return body.meters_per_pixel
    west, south, east, north = body.bbox
    span = (east - west) % 360 or 360
    return max(1e-6, span * 111320 * max(.01, math.cos(math.radians((south+north)/2))) / body.width)


def feature_for(row, weight=0):
    return {'type':'Feature','id':row.id,'geometry':row.geometry,'properties':row.properties,
            '__object':{'object_id':row.id,'feature_index':row.feature_index,
                        'asset':{'asset_id':row.asset_id,'version':row.asset_version},'weight':weight}}


def load_display(session, identity):
    return session.get(SpatialObject,identity,options=[load_only(SpatialObject.id,SpatialObject.asset_id,
        SpatialObject.asset_version,SpatialObject.feature_index,SpatialObject.geometry,SpatialObject.properties)])


def road_batches(groups):
    batch, size = [], 0
    for group in groups:
        if batch and size + len(group) > 256:
            yield batch
            batch, size = [], 0
        batch.append(group)
        size += len(group)
    if batch:
        yield batch


def explicit_road(properties):
    return 'highway' in properties or ('fclass' in properties and classification(properties) in RANK)


def road_features(session, body, windows, mpp, mask, *, explicit_only=False):
    degrees, segments = Counter(), {}
    for row in candidates(session, body.asset_id, body.version, windows, properties=True, endpoints=True):
        if row.geometry_type not in ('LineString', 'MultiLineString'):
            continue
        endpoints = tuple(tuple(point) for pair in json.loads(row.endpoints) for point in pair)
        degrees.update(endpoints)
        properties = json.loads(row.properties)
        rank = road_rank(properties, mpp, body.road_max_level)
        if rank is not None and (not explicit_only or explicit_road(properties)):
            key = signature({'id': row.id, 'properties': properties})
            segments[row.id] = (rank, key, endpoints if row.geometry_type == 'LineString' else ())

    prepare(mask)
    for batch in road_batches(road_groups(segments, degrees)):
        # The pick endpoint accepts at most 2,000 source IDs per display line.
        identities = [identity for group in batch if len(group) <= 2000 for identity in group]
        rows = {row.id: row for row in session.execute(select(
            SpatialObject.id, SpatialObject.asset_id, SpatialObject.asset_version,
            SpatialObject.feature_index, SpatialObject.geometry, SpatialObject.properties,
        ).where(SpatialObject.id.in_(identities)))} if identities else {}
        for group in batch:
            if len(group) > 2000:
                yield None
                continue
            representative = rows[group[0]]
            line = (line_merge(MultiLineString([rows[identity].geometry['coordinates'] for identity in group]))
                    if len(group) > 1 else shape(representative.geometry))
            if not mask.intersects(line):
                continue
            clipped = line if mask.covers(line) else line.intersection(mask)
            # Intersections at the viewport boundary may contain isolated points.
            if clipped.geom_type == 'GeometryCollection':
                parts = [part for part in clipped.geoms if part.geom_type == 'LineString']
                clipped = MultiLineString(parts)
            if clipped.is_empty or clipped.geom_type not in ('LineString', 'MultiLineString'):
                continue
            feature = feature_for(representative)
            geometry = mapping(clipped)
            lines = [geometry['coordinates']] if clipped.geom_type == 'LineString' else geometry['coordinates']
            # Only exact consecutive duplicates may be removed; keep every bend.
            cleaned = [[point for index, point in enumerate(line) if index == 0 or point != line[index - 1]]
                       for line in lines]
            feature['geometry'] = {**geometry, 'coordinates': cleaned[0] if clipped.geom_type == 'LineString' else cleaned}
            feature['__object']['source_object_ids'] = group
            feature['__display'] = {'road_class': classification(representative.properties), 'road_rank': segments[representative.id][0]}
            yield feature


@router.post('/viewport')
def viewport(body: ViewportInput, session: SessionDep):
    category = validate_reference(session,body)
    windows, mpp = bbox_windows(body.bbox), meters_per_pixel(body)
    mask = parse_bbox(','.join(map(str,body.bbox)))
    span = (body.bbox[2]-body.bbox[0]) % 360 or 360
    tolerance = max(span/body.width,(body.bbox[3]-body.bbox[1])/body.height)*.75
    truncated = False
    if category == '道路':
        display = road_features(session, body, windows, mpp, mask)
    elif category == 'POI':
        from .poi_style import poi_style
        west,south,east,north = body.bbox
        columns,rows = min(128,max(1,body.width//32)),min(128,max(1,body.height//32))
        cells = {}
        for row in candidates(session,body.asset_id,body.version,windows,point_only=True,properties=True):
            style = poi_style(json.loads(row.properties),mpp)
            if not style['eligible']:
                continue
            cell = (min(columns-1,int(((row.west-west)%360)/span*columns)),
                    min(rows-1,int((row.south-south)/max(north-south,1e-12)*rows)))
            weight = row.weight if isinstance(row.weight,(int,float)) and math.isfinite(row.weight) else 0
            key = (-weight,-style['priority'],row.id)
            bucket = cells.setdefault(cell,[])
            bucket.append((key,row.id,weight,style))
            bucket.sort(key=lambda value:value[0])
            del bucket[4:]
        ranked = sorted((item for bucket in cells.values() for item in bucket),key=lambda value:value[0])
        truncated = len(ranked) > MAX_FEATURES
        def selected_pois():
            for _,identity,weight,style in ranked[:MAX_FEATURES]:
                feature = feature_for(load_display(session,identity),weight)
                feature['__display'] = {'poi_category':style['category'],'priority':style['priority'],'name':style['name']}
                yield feature
        display = selected_pois()
    else:
        def generic_features():
            yield from road_features(session, body, windows, mpp, mask, explicit_only=True)
            for row in candidates(session,body.asset_id,body.version,windows,properties=True,endpoints=True):
                if row.geometry_type == 'Point' or not explicit_road(json.loads(row.properties)):
                    yield feature_for(load_display(session,row.id),row.weight)
        display = generic_features()
    features,vertex_count,byte_count = [],0,128
    for feature in display:
        if feature is None:
            truncated = True
            continue
        geometry = feature['geometry']
        if not geometry:
            continue
        if '__display' not in feature and geometry['type'] != 'Point':
            clipped = shape(geometry).intersection(mask).simplify(tolerance,preserve_topology=True)
            if clipped.is_empty:
                continue
            geometry = mapping(clipped)
        if len(features) >= MAX_FEATURES:
            truncated = True
            break
        feature = {**feature,'geometry':geometry}
        size = len(json.dumps(feature,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8'))+1
        amount = vertices(geometry)
        if vertex_count+amount > MAX_VERTICES or byte_count+size > MAX_BYTES:
            truncated = True
            continue
        features.append(feature)
        vertex_count += amount
        byte_count += size
    return {'type':'FeatureCollection','features':features,'truncated':truncated}


def road_source_ids(session, body):
    if body.object_ids:
        return set(body.object_ids)
    from .render_models import RenderJob
    from .rendering import RENDER_DIR
    job = session.get(RenderJob, body.render_key)
    if not job or job.asset_id != body.asset_id or job.version != body.version or job.status != 'succeeded':
        raise ApiProblem(422, 'VALIDATION_ERROR', '显示道路组不属于当前图层资产版本')
    try:
        with (RENDER_DIR / job.key / 'road_sources.jsonl').open(encoding='utf8') as source:
            for line in source:
                group = json.loads(line)
                if group['group_id'] == body.display_group_id:
                    identities = set(group['source_object_ids'])
                    if identities:
                        return identities
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ApiProblem(409, 'RENDER_UNAVAILABLE', '显示道路来源映射不可用') from error
    raise ApiProblem(422, 'VALIDATION_ERROR', '显示道路组不存在')


@router.post('/road-pick')
def road_pick(body: RoadPickInput, session: SessionDep):
    validate_reference(session,body)
    identities = sorted(road_source_ids(session, body))
    projection = Transformer.from_crs('EPSG:4326',CRS.from_proj4(f'+proj=aeqd +lat_0={body.latitude} +lon_0={body.longitude} +datum=WGS84'),always_xy=True)
    origin = Point(0,0)
    nearest, nearest_key = None, None
    # Groups can exceed the legacy 2,000-ID request bound; keep geometry reads bounded.
    for offset in range(0, len(identities), 256):
        batch = identities[offset:offset + 256]
        rows = session.scalars(select(SpatialObject).where(SpatialObject.id.in_(batch),
            SpatialObject.asset_id==body.asset_id,SpatialObject.asset_version==body.version)).all()
        if len(rows) != len(batch) or any(not row.geometry or row.geometry['type'] not in ('LineString','MultiLineString') for row in rows):
            raise ApiProblem(422,'VALIDATION_ERROR','来源路段不属于当前图层资产版本')
        for row in rows:
            key = (transform(shape(row.geometry),projection.transform,interleaved=False).distance(origin),row.id)
            if nearest_key is None or key < nearest_key:
                nearest, nearest_key = row, key
    from .object_queries import _output
    return _output(nearest,{},preferred_layer=body.layer_id)


def nearby_windows(longitude, latitude, radius):
    # A conservative angular cap; ellipsoidal meridional radius is >= 6,335 km.
    angle = radius / 6_335_000
    delta_lat = math.degrees(angle)
    south, north = max(-90, latitude - delta_lat), min(90, latitude + delta_lat)
    if south == -90 or north == 90:
        return [(-180, south, 180, north)]
    delta_lon = math.degrees(math.asin(min(1, math.sin(angle) / math.cos(math.radians(latitude)))))
    west, east = longitude - delta_lon, longitude + delta_lon
    if west < -180:
        return [(west + 360, south, 180, north), (-180, south, east, north)]
    if east > 180:
        return [(west, south, 180, north), (-180, south, east - 360, north)]
    return [(west, south, east, north)]


@router.post('/nearby')
def nearby(body: NearbyInput, session: SessionDep):
    windows = nearby_windows(body.longitude, body.latitude, body.radius_m)
    ranked, unavailable, seen = [], [], set()
    for reference in body.layers:
        key = (reference.layer_id, reference.asset_id, reference.version)
        if key in seen:
            continue
        seen.add(key)
        try:
            category = validate_reference(session, reference)
        except ApiProblem as error:
            if error.code in ('OBJECT_INDEX_UNAVAILABLE', 'ASSET_UNAVAILABLE'):
                unavailable.append(reference.layer_id)
                continue
            raise
        if category != 'POI':
            raise ApiProblem(422, 'VALIDATION_ERROR', '附近查询仅支持 POI 图层')
        for row in candidates(session, reference.asset_id, reference.version, windows, point_only=True):
            distance = GEOD.inv(body.longitude, body.latitude, row.west, row.south)[2]
            if distance <= body.radius_m:
                ranked.append((distance, row.id, reference.layer_id))
                ranked.sort()
                del ranked[body.limit:]
    records = lightweight(session, [identity for _, identity, _ in ranked])
    return {'items': [{**light_output(records[identity], layer_id), 'distance_m': distance}
                      for distance, identity, layer_id in ranked], 'unavailable_layers': unavailable}


@router.get('/objects/{identity}')
def detail(identity: str, session: SessionDep):
    record = lightweight(session, [identity]).get(identity)
    if record is None:
        raise ApiProblem(404, 'OBJECT_NOT_FOUND', '对象不存在')
    _available(session, session.get(Asset, record['asset_id']), record['asset_version'])
    return light_output(record)

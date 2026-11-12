"""Validated, version-scoped semantic source, independent of upload retention."""
import hashlib
import json

from sqlalchemy import insert, select, update

from app.database import SessionLocal
from app.services.geojson_stream import check_cancel
from app.models import Asset, AssetVersion, GeoJSONMember, GeoJSONSnapshot, ObjectIndex, SpatialObject

BATCH_SIZE = 500


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'), sort_keys=True)


def _hash(digest, value):
    digest.update(encode(value).encode('utf8'))
    digest.update(b'\n')


def feature_value(row):
    return {**(row.feature_members or {}), 'type': 'Feature', 'geometry': row.geometry,
            'properties': None if row.properties_null else row.properties}


def iter_features(session, asset_id, version):
    """Keyset batches keep memory and database cursor lifetimes bounded."""
    after = -1
    while True:
        rows = list(session.scalars(select(SpatialObject).where(
            SpatialObject.asset_id == asset_id, SpatialObject.asset_version == version,
            SpatialObject.feature_index > after).order_by(SpatialObject.feature_index).limit(BATCH_SIZE)))
        if not rows:
            return
        for row in rows:
            check_cancel(None)
            yield row
        after = rows[-1].feature_index


def iter_members(session, asset_id, version):
    for row in session.scalars(select(GeoJSONMember).where(
            GeoJSONMember.asset_id == asset_id, GeoJSONMember.asset_version == version)
            .order_by(GeoJSONMember.ordinal).execution_options(yield_per=BATCH_SIZE)):
        check_cancel(None)
        yield row.name, row.value
    for row in iter_features(session, asset_id, version):
        yield None, feature_value(row)


def ready_snapshot(session, asset_id, version):
    """Only the transactional full-content validator can mark a snapshot ready."""
    snapshot = session.get(GeoJSONSnapshot, (asset_id, version))
    return snapshot if (snapshot and snapshot.validated and snapshot.feature_count >= 0
                        and len(snapshot.sha256) == 64) else None


class SnapshotWriter:
    def __init__(self, session, asset_id, version, cancel=None):
        self.session, self.asset_id, self.version, self.cancel = session, asset_id, version, cancel
        self.features_hash, self.members_hash = hashlib.sha256(), hashlib.sha256()
        self.count, self.member_count = 0, 0
        self.snapshot = GeoJSONSnapshot(asset_id=asset_id, asset_version=version,
                                       feature_count=0, sha256='', validated=False)
        session.add(self.snapshot)
        session.flush()

    def member(self, name, value):
        _hash(self.members_hash, [name, value])
        self.session.execute(insert(GeoJSONMember).values(asset_id=self.asset_id, asset_version=self.version,
                             ordinal=self.member_count, name=name, value=value))
        self.member_count += 1

    def feature(self, feature):
        _hash(self.features_hash, {**feature, 'geometry': feature.get('geometry'), 'properties': feature.get('properties')})
        self.count += 1
        return {'feature_members': {k: v for k, v in feature.items() if k not in ('type', 'geometry', 'properties')},
                'properties_null': feature.get('properties') is None}

    def complete(self):
        self.session.flush()
        features_hash, members_hash = hashlib.sha256(), hashlib.sha256()
        for name, value in self.session.execute(select(GeoJSONMember.name, GeoJSONMember.value).where(
                GeoJSONMember.asset_id == self.asset_id, GeoJSONMember.asset_version == self.version)
                .order_by(GeoJSONMember.ordinal).execution_options(yield_per=BATCH_SIZE)):
            check_cancel(self.cancel)
            _hash(members_hash, [name, value])
        count = 0
        for row in iter_features(self.session, self.asset_id, self.version):
            check_cancel(self.cancel)
            if row.feature_index != count or row.feature_members is None:
                raise ValueError('完整快照要素顺序无效')
            _hash(features_hash, feature_value(row))
            count += 1
        if (count != self.count or features_hash.digest() != self.features_hash.digest()
                or members_hash.digest() != self.members_hash.digest()):
            raise ValueError('完整快照与原文件内容不一致')
        self.snapshot.feature_count = count
        self.snapshot.sha256 = hashlib.sha256(members_hash.digest() + features_hash.digest()).hexdigest()
        self.snapshot.validated = True
        self.session.flush()
        return self.snapshot


def ensure_snapshot(session, asset_id, version, *, cancel=None):
    """Backfill legacy metadata only after raw bytes and indexed records agree.

    Caller owns commit/rollback. Failures never leave a partially trusted snapshot.
    """
    ready = ready_snapshot(session, asset_id, version)
    if ready:
        return ready
    asset = session.get(Asset, asset_id)
    asset_version = session.get(AssetVersion, (asset_id, version))
    state = session.get(ObjectIndex, (asset_id, version))
    if not asset or asset.type != 'geojson' or not asset_version or not state or state.status != 'ready':
        return None
    from app.services.object_index import _records
    with session.begin_nested():
        old = session.get(GeoJSONSnapshot, (asset_id, version))
        if old:
            session.delete(old)
            session.flush()
        writer = SnapshotWriter(session, asset_id, version, cancel)
        rows = iter(iter_features(session, asset_id, version))
        for record in _records(asset, asset_version, cancel, snapshot=writer):
            row = next(rows, None)
            if (row is None or row.id != record['id'] or row.feature_index != record['feature_index']
                    or row.geometry != record['geometry'] or row.properties != record['properties']):
                raise ValueError('旧对象索引与原文件的顺序、属性或几何不一致')
            session.execute(update(SpatialObject).where(SpatialObject.id == row.id).values(
                feature_members=record['feature_members'], properties_null=record['properties_null']))
        if next(rows, None) is not None:
            raise ValueError('旧对象索引要素数量与原文件不一致')
        return writer.complete()


def iter_export(asset_id, version, identified=False):
    """Streaming responses own a session instead of using a request's closed one."""
    with SessionLocal() as session:
        # sqlite3's legacy transaction mode does not BEGIN for SELECT. Pin a
        # database read snapshot before the preflight, so a concurrent cascade
        # cannot silently truncate subsequent keyset batches or metadata.
        if session.get_bind().dialect.name == 'sqlite':
            session.connection().exec_driver_sql('BEGIN')
        if not ready_snapshot(session, asset_id, version):
            raise ValueError('完整 GeoJSON 快照尚未就绪')
        yield '{"type":"FeatureCollection","features":['
        first = True
        for row in iter_features(session, asset_id, version):
            value = feature_value(row)
            if identified:
                value['__object'] = {'object_id': row.id, 'feature_index': row.feature_index}
            yield ('' if first else ',') + encode(value)
            first = False
        yield ']'
        for name, value in session.execute(select(GeoJSONMember.name, GeoJSONMember.value).where(
                GeoJSONMember.asset_id == asset_id, GeoJSONMember.asset_version == version)
                .order_by(GeoJSONMember.ordinal).execution_options(yield_per=BATCH_SIZE)):
            if name != 'type':
                yield ',' + encode(name) + ':' + encode(value)
        yield '}'

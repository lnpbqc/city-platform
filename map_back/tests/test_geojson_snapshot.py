import json

import pytest
from sqlalchemy import delete, select

from app.assets import published_files
from app.database import SessionLocal
from app.geojson_snapshot import ensure_snapshot, iter_export, ready_snapshot
from app.models import Asset, GeoJSONSnapshot, ObjectIndex, SpatialObject
from app.poi_mutations import PoiChange, rewrite
from test_layers import upload


def document(count=3):
    return {'type': 'FeatureCollection', 'source': {'name': '完整来源'}, 'bbox': [0, 0, 1, 1],
            'features': [{'type': 'Feature', 'id': '重复', '__object': {'user': True},
                          'foreign': {'nested': [i]}, 'properties': None if i == 0 else {},
                          'geometry': {'type': 'Point', 'coordinates': [0.5, 0.5]}}
                         for i in range(count)]}


def test_source_removal_keeps_semantic_export_stable_identity_and_poi_edit(client, tmp_path):
    original = document()
    response = client.post('/api/layers/upload', data={'name': 'POI', 'category': 'POI', 'type': 'geojson'},
                           files={'file': ('poi.geojson', json.dumps(original), 'application/geo+json')})
    assert response.status_code == 201, response.text
    layer = response.json()
    aid, version = layer['asset_id'], layer['asset_version']
    with SessionLocal() as session:
        snapshot = ready_snapshot(session, aid, version)
        assert snapshot and snapshot.feature_count == 3 and len(snapshot.sha256) == 64
        root, _, entry = published_files(session.get(Asset, aid))
        (root / entry).unlink()
        rows = list(session.scalars(select(SpatialObject).where(SpatialObject.asset_id == aid).order_by(SpatialObject.feature_index)))
        ids = [row.id for row in rows]
    assert json.loads(''.join(iter_export(aid, version))) == original
    identified = json.loads(''.join(iter_export(aid, version, identified=True)))
    assert [feature['__object'] for feature in identified['features']] == [
        {'object_id': oid, 'feature_index': i} for i, oid in enumerate(ids)]
    with SessionLocal() as session:
        target = tmp_path / 'edited.geojson'
        rewrite(session, layer['id'], PoiChange(asset_id=aid, version=version, operation='update',
                object_id=ids[0], feature={'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [0.6, 0.5]},
                                         'properties': {'name': '新名'}}), target)
        changed = json.loads(target.read_text(encoding='utf8'))
        assert changed['features'][0]['foreign'] == original['features'][0]['foreign']
        assert changed['features'][0]['id'] == '重复' and 'bbox' not in changed
        assert changed['features'][1:] == original['features'][1:]
        from app.object_index import index_asset
        session.execute(delete(ObjectIndex).where(ObjectIndex.asset_id == aid))
        assert index_asset(session, session.get(Asset, aid)).status == 'ready'


def test_legacy_backfill_verifies_content_and_is_repeatable(client):
    original = document(2)
    layer = upload(client, json.dumps(original).encode()).json()
    aid, version = layer['asset_id'], layer['asset_version']
    with SessionLocal() as session:
        session.execute(delete(GeoJSONSnapshot).where(GeoJSONSnapshot.asset_id == aid))
        for row in session.scalars(select(SpatialObject).where(SpatialObject.asset_id == aid)):
            row.feature_members = None
            row.properties_null = False
        session.commit()
        first = ensure_snapshot(session, aid, version)
        digest = first.sha256
        session.commit()
        assert ensure_snapshot(session, aid, version).sha256 == digest
    assert json.loads(''.join(iter_export(aid, version))) == original


def test_legacy_mismatch_never_marks_snapshot_ready(client):
    layer = upload(client, json.dumps(document()).encode()).json()
    aid, version = layer['asset_id'], layer['asset_version']
    with SessionLocal() as session:
        session.execute(delete(GeoJSONSnapshot).where(GeoJSONSnapshot.asset_id == aid))
        row = session.scalar(select(SpatialObject).where(SpatialObject.asset_id == aid))
        row.properties = {'tampered': True}
        session.commit()
        with pytest.raises(ValueError, match='顺序、属性或几何'):
            ensure_snapshot(session, aid, version)
        assert ready_snapshot(session, aid, version) is None


def test_export_uses_fixed_keyset_batches(client, monkeypatch):
    from app import geojson_snapshot
    monkeypatch.setattr(geojson_snapshot, 'BATCH_SIZE', 2)
    original = document(7)
    layer = upload(client, json.dumps(original).encode()).json()
    assert json.loads(''.join(iter_export(layer['asset_id'], layer['asset_version']))) == original


def test_stream_keeps_read_snapshot_when_asset_deleted_between_batches(client):
    original = document(600)
    layer = upload(client, json.dumps(original).encode()).json()
    stream = iter_export(layer['asset_id'], layer['asset_version'])
    try:
        prefix = next(stream) + next(stream)
        # The first feature has loaded batch one. Delete from another connection
        # before the next batch and collection metadata are read.
        assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
        assert client.delete(f"/api/assets/{layer['asset_id']}").status_code == 204
        exported = json.loads(prefix + ''.join(stream))
        assert exported == original
    finally:
        stream.close()


def test_canonical_reader_honors_poi_disconnect_cancellation(client):
    from app.geojson_snapshot import iter_members
    from app.geojson_stream import cancellation
    layer = upload(client, json.dumps(document()).encode()).json()
    def cancelled():
        raise RuntimeError('disconnected')
    token = cancellation.set(cancelled)
    try:
        with SessionLocal() as session:
            with pytest.raises(RuntimeError, match='disconnected'):
                next(iter_members(session, layer['asset_id'], layer['asset_version']))
    finally:
        cancellation.reset(token)

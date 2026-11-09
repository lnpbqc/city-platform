import json
import pytest
from app import uploads


def test_limit_is_one_gib():
    assert uploads.GEOJSON_LIMIT == 1_073_741_824


def test_restart_reuses_published_geometry_metadata_but_checks_content(client, monkeypatch):
    from app.database import SessionLocal, FILES_DIR
    from app.models import Asset, AssetVersion, Layer
    from app.layer_catalog import initialize_catalog
    from app import geojson_stream
    doc = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [113, 23]}, 'properties': {}}]}
    response = client.post('/api/layers/upload', data={'name': 'restart', 'type': 'geojson'}, files={'file': ('restart.geojson', json.dumps(doc))})
    assert response.status_code == 201, response.text
    record = response.json()
    with SessionLocal() as session:
        initialize_catalog(session)
    def forbidden(*args, **kwargs):
        raise AssertionError('Restart must reuse immutable geometry metadata')
    monkeypatch.setattr(geojson_stream, 'members', forbidden)
    with SessionLocal() as session:
        version = session.get(AssetVersion, (record['asset_id'], record['asset_version']))
        bounds = version.bounds
        initialize_catalog(session)
        assert session.get(Asset, record['asset_id']).status == 'active'
        assert session.get(Layer, record['id']).orderable
        assert version.bounds == bounds
        with (FILES_DIR / record['asset_id'] / 'data.geojson').open('ab') as stream:
            stream.write(b' ')
        initialize_catalog(session)
        assert session.get(Asset, record['asset_id']).status == 'unsafe'


def test_stream_bom_tail_and_crs(tmp_path):
    from app.geojson_stream import features
    path = tmp_path / 'data.geojson'
    path.write_text('\ufeff{"features":[],"type":"FeatureCollection"}', encoding='utf8')
    assert list(features(path)) == []
    for payload in ['{"type":"FeatureCollection","features":[]} junk', '{"type":"FeatureCollection","features":[],"crs":{}}', '{"type":"FeatureCollection"}']:
        path.write_text(payload, encoding='utf8')
        with pytest.raises(ValueError):
            list(features(path))


def test_single_poi_mutation(client):
    doc = {'type':'FeatureCollection', 'custom':{'keep':True}, 'features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[121,25]},'properties':{'name':'old','keep':1}}]}
    response = client.post('/api/layers/upload',data={'name':'poi','type':'geojson','category':'POI'},files={'file':('p.geojson',json.dumps(doc))})
    assert response.status_code == 201, response.text
    layer = response.json()
    item = client.get('/api/objects',params={'layer_id':layer['id']}).json()['items'][0]
    body = {'asset_id':layer['asset_id'],'version':layer['asset_version'],'operation':'update','object_id':item['object_id'],'feature':{'type':'Feature','geometry':{'type':'Point','coordinates':[121,25]},'properties':{'name':'new','keep':1}}}
    result = client.post(f"/api/layers/{layer['id']}/poi-features",json=body)
    assert result.status_code == 200, result.text
    saved = client.get(result.json()['url']).json()
    assert saved['custom'] == {'keep':True}
    assert saved['features'][0]['properties']['name'] == 'new'
    stale = client.post(f"/api/layers/{layer['id']}/poi-features",json=body)
    assert stale.status_code == 409


def test_receive_exact_limit_and_one_extra_byte():
    import asyncio
    from fastapi import HTTPException
    class File:
        def __init__(self, size):
            self.remaining = size
        async def read(self, size):
            length = min(self.remaining, size)
            self.remaining -= length
            return b'x' * length
    class Sink:
        def open(self, mode):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def write(self, value):
            pass
    asyncio.run(uploads.receive(File(uploads.GEOJSON_LIMIT), Sink(), uploads.GEOJSON_LIMIT))
    with pytest.raises(HTTPException) as error:
        asyncio.run(uploads.receive(File(uploads.GEOJSON_LIMIT + 1), Sink(), uploads.GEOJSON_LIMIT))
    assert error.value.status_code == 413


def test_stream_foreign_feature_member_and_cancellation(tmp_path):
    from app.geojson_stream import features
    path = tmp_path / 'p.geojson'
    path.write_text('{"type":"FeatureCollection","feature":"foreign","features":[]}', encoding='utf8')
    assert list(features(path)) == []
    def cancel():
        raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError, match='cancelled'):
        list(features(path, cancel))


def test_upload_never_reads_whole_geojson(client, monkeypatch):
    from pathlib import Path
    def forbidden(*args, **kwargs):
        raise AssertionError('GeoJSON must be streamed')
    monkeypatch.setattr(Path, 'read_text', forbidden)
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    result = client.post('/api/layers/upload', data={'name':'streamed','type':'geojson'},
                         files={'file':('p.geojson','{"type":"FeatureCollection","features":[]}', 'application/json')})
    assert result.status_code == 201, result.text


def test_invalid_index_is_not_published(client, monkeypatch):
    from types import SimpleNamespace
    from app import main
    before = set(main.FILES_DIR.iterdir())
    monkeypatch.setattr(main, 'index_asset', lambda *args, **kwargs: SimpleNamespace(status='invalid', error='broken index'))
    result = client.post('/api/layers/upload', data={'name':'broken','type':'geojson'},
                         files={'file':('p.geojson','{"type":"FeatureCollection","features":[]}', 'application/json')})
    assert result.status_code == 422
    assert set(main.FILES_DIR.iterdir()) == before
    assert not client.get('/api/layers').json()


def test_metadata_streams_dateline_features(tmp_path):
    from app.asset_metadata import build_metadata
    path = tmp_path / 'p.geojson'
    path.write_text(json.dumps({'type':'FeatureCollection','features':[
        {'type':'Feature','properties':{},'geometry':{'type':'Point','coordinates':[longitude,20]}}
        for longitude in [179,-179,178]
    ]}), encoding='utf8')
    bounds = build_metadata(tmp_path, [{'path':path.name,'size':path.stat().st_size}], path.name, 'geojson')['bounds']
    assert bounds['west'] == 178 and bounds['east'] == -179

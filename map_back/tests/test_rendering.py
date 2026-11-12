"""Retention integration uses only conftest's temporary database and files."""
from datetime import timedelta
import hashlib
import json
import shutil
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.database import FILES_DIR, STORAGE_DIR, SessionLocal
from app.main import app
from app.models import Asset, GeoJSONSnapshot
from app.render_models import RenderJob
from app import rendering
from test_layers import GEO, upload


@pytest.fixture(autouse=True)
def render_environment(monkeypatch):
    monkeypatch.setenv('CITY_TILE_SERVICE_URL', '')
    monkeypatch.setenv('CITY_TILE_TOKEN', 'test-internal-token')
    # These tables deliberately keep tombstones beyond asset deletion.
    with SessionLocal() as session:
        session.execute(delete(RenderJob))
        session.commit()
    yield
    with SessionLocal() as session:
        session.execute(delete(RenderJob))
        session.commit()
    for folder in (rendering.RENDER_DIR, STORAGE_DIR / 'expired-sources'):
        if folder.exists():
            shutil.rmtree(folder)


def published(client, tmp_path, document=None):
    document = document or GEO
    response = upload(client, json.dumps(document).encode())
    assert response.status_code == 201, response.text
    layer = response.json()
    with SessionLocal() as session:
        job = rendering.enqueue(session, layer['asset_id'], layer['asset_version'])
        session.commit()
        key = job.key
        snapshot = session.get(GeoJSONSnapshot, (job.asset_id, job.version))
        manifest = {'asset_id': job.asset_id, 'version': job.version, 'profile': job.profile,
                    'recipe': job.recipe, 'source_layer': 'data', 'minzoom': 0, 'maxzoom': 18,
                    'bounds': [114, 22, 115, 23], 'source_snapshot_sha256': snapshot.sha256,
                    'source_feature_count': snapshot.feature_count}
    header = bytearray(127)
    header[:8], header[99] = b'PMTiles\x03', 1
    archive = bytes(header) + b'test archive payload'
    manifest['pmtiles_sha256'] = hashlib.sha256(archive).hexdigest()
    bundle = tmp_path / f'{key}.zip'
    with ZipFile(bundle, 'w') as output:
        output.writestr('manifest.json', json.dumps(manifest))
        output.writestr('map.pmtiles', archive)
    rendering.publish(key, bundle)
    with SessionLocal() as session:
        assert session.get(RenderJob, key).status == 'succeeded'
    return layer, key, archive


def source_path(layer):
    return FILES_DIR / layer['asset_id'] / 'data.geojson'


def test_archive_range_and_token_protected_source(client, tmp_path):
    layer, key, archive = published(client, tmp_path)
    url = f'/api/render-files/{key}/map.pmtiles'
    response = client.get(url, headers={'Range': 'bytes=0-7'})
    assert response.status_code == 206 and response.content == b'PMTiles\x03'
    assert response.headers['content-range'] == f'bytes 0-7/{len(archive)}'
    assert response.headers['etag'] == '"' + hashlib.sha256(archive).hexdigest() + '"'
    assert 'content-encoding' not in response.headers
    internal = f"/internal/render-source/{layer['asset_id']}/{layer['asset_version']}"
    assert client.get(internal).status_code == 401
    assert client.get(internal, headers={'Authorization': 'Bearer wrong'}).status_code == 401
    exported = client.get(internal, headers={'Authorization': 'Bearer test-internal-token'})
    assert exported.status_code == 200
    identity = exported.json()['features'][0]['__object']
    assert identity['feature_index'] == 0 and identity['object_id']


def test_archive_conditional_request(client, tmp_path):
    _, key, archive = published(client, tmp_path)
    response = client.get(f'/api/render-files/{key}/map.pmtiles',
                          headers={'If-None-Match': '"' + hashlib.sha256(archive).hexdigest() + '"'})
    assert response.status_code == 304 and response.content == b''


def test_exact_seven_days_expiry_keeps_canonical_export_and_restart(client, tmp_path):
    layer, key, _ = published(client, tmp_path)
    with SessionLocal() as session:
        job = session.get(RenderJob, key)
        assert job.source_expires_at == job.ready_at + timedelta(days=7)
        expiry = job.source_expires_at
    rendering.expire_sources(expiry - timedelta(microseconds=1))
    assert source_path(layer).is_file()
    rendering.expire_sources(expiry)
    assert not source_path(layer).exists()
    with SessionLocal() as session:
        assert session.get(RenderJob, key).source_state == 'expired'
        assert session.get(Asset, layer['asset_id']).byte_size == 0
    download = client.get(f"/api/assets/{layer['asset_id']}/download")
    assert download.status_code == 410 and download.json()['code'] == 'SOURCE_EXPIRED'
    export = f"/api/assets/{layer['asset_id']}/versions/{layer['asset_version']}/geojson"
    assert client.get(export).json() == GEO
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    restored = client.post('/api/layers', json={name: layer[name] for name in ('name', 'type', 'category', 'source', 'url')})
    assert restored.status_code == 201, restored.text
    assert restored.json()['asset_id'] == layer['asset_id']
    with TestClient(app) as restarted:
        assert restarted.get(f"/api/assets/{layer['asset_id']}").json()['status'] == 'active'
        assert restarted.get(export).json() == GEO
    assert client.post('/api/assets/reconcile').status_code == 200
    assert client.get(f"/api/assets/{layer['asset_id']}").json()['status'] == 'active'
    assert client.get(export).json() == GEO


@pytest.mark.parametrize('unsafe', ['failed', 'no_snapshot', 'no_archive', 'changed_archive'])
def test_unsafe_source_never_expires(client, tmp_path, unsafe):
    layer, key, _ = published(client, tmp_path)
    with SessionLocal() as session:
        job = session.get(RenderJob, key)
        expiry = job.source_expires_at
        if unsafe == 'failed':
            job.status = 'failed'
        elif unsafe == 'no_snapshot':
            session.execute(delete(GeoJSONSnapshot).where(GeoJSONSnapshot.asset_id == layer['asset_id']))
        elif unsafe == 'no_archive':
            (rendering.RENDER_DIR / key / 'map.pmtiles').unlink()
        else:
            (rendering.RENDER_DIR / key / 'map.pmtiles').write_bytes(b'tampered archive')
        session.commit()
    rendering.expire_sources(expiry)
    assert source_path(layer).is_file()
    with SessionLocal() as session:
        assert session.get(RenderJob, key).source_state == 'retained'


def test_retention_recovers_both_sides_of_interrupted_commit(client, tmp_path):
    layer, key, _ = published(client, tmp_path)
    staged = STORAGE_DIR / 'expired-sources' / key
    staged.parent.mkdir(exist_ok=True)
    source_path(layer).rename(staged)
    rendering.recover_retention()
    assert source_path(layer).is_file() and not staged.exists()
    source_path(layer).rename(staged)
    with SessionLocal() as session:
        session.get(RenderJob, key).source_state = 'expired'
        session.commit()
    rendering.recover_retention()
    assert not staged.exists() and not source_path(layer).exists()


def test_asset_delete_preserves_references_then_cancels_and_removes_derivatives(client, tmp_path):
    layer, key, _ = published(client, tmp_path)
    asset_url = f"/api/assets/{layer['asset_id']}"
    assert client.delete(asset_url).status_code == 409
    assert (rendering.RENDER_DIR / key / 'map.pmtiles').is_file()
    assert client.delete(f"/api/layers/{layer['id']}").status_code == 204
    assert client.delete(asset_url).status_code == 204
    assert not (rendering.RENDER_DIR / key).exists()
    assert not source_path(layer).exists()
    with SessionLocal() as session:
        job = session.get(RenderJob, key)
        assert job and job.status == 'cancelled'
        assert session.get(GeoJSONSnapshot, (layer['asset_id'], layer['asset_version'])) is None


def test_daily_check_after_startup_before_three_am():
    from datetime import datetime
    # UTC+8: a startup check at 01:00 must still schedule today's 03:00.
    assert rendering.next_source_check(datetime(2026, 11, 9, 17)) == datetime(2026, 11, 9, 19)
    assert rendering.next_source_check(datetime(2026, 11, 9, 19)) == datetime(2026, 11, 10, 19)


def test_default_service_configuration_uses_application_port(tmp_path, monkeypatch):
    monkeypatch.setattr(rendering, 'STORAGE_DIR', tmp_path)
    monkeypatch.delenv('CITY_TILE_BACKEND_ORIGIN', raising=False)
    assert rendering.configuration()['backend'] == 'http://127.0.0.1:8000'
    (tmp_path / 'tile-service.json').write_text(json.dumps({'backend': 'http://localhost:9000'}), encoding='utf8')
    assert rendering.configuration()['backend'] == 'http://localhost:9000'
    monkeypatch.setenv('CITY_TILE_BACKEND_ORIGIN', 'http://localhost:9001')
    assert rendering.configuration()['backend'] == 'http://localhost:9001'


def test_republication_commit_failure_restores_previous_archive(client, tmp_path, monkeypatch):
    from sqlalchemy.orm import Session
    layer, key, archive = published(client, tmp_path)
    with SessionLocal() as session:
        session.get(RenderJob, key).status = 'running'
        session.commit()
    original_commit = Session.commit

    def fail_publication(session):
        if any(isinstance(row, RenderJob) and row.status == 'succeeded' for row in session.dirty):
            raise RuntimeError('injected database failure')
        return original_commit(session)

    monkeypatch.setattr(Session, 'commit', fail_publication)
    with pytest.raises(RuntimeError, match='injected'):
        rendering.publish(key, tmp_path / f'{key}.zip')
    assert (rendering.RENDER_DIR / key / 'map.pmtiles').read_bytes() == archive
    assert not (rendering.RENDER_DIR / (key + '.previous')).exists()
    with SessionLocal() as session:
        assert session.get(RenderJob, key).status == 'running'
    assert source_path(layer).is_file()


def test_expiry_commit_failure_restores_upload(client, tmp_path, monkeypatch):
    from sqlalchemy.orm import Session
    layer, key, _ = published(client, tmp_path)
    before = source_path(layer).read_bytes()
    with SessionLocal() as session:
        expiry = session.get(RenderJob, key).source_expires_at
    original_commit = Session.commit

    def fail_expiry(session):
        if any(isinstance(row, RenderJob) and row.source_state == 'expired' for row in session.dirty):
            raise RuntimeError('injected database failure')
        return original_commit(session)

    monkeypatch.setattr(Session, 'commit', fail_expiry)
    with pytest.raises(RuntimeError, match='injected'):
        rendering.expire_sources(expiry)
    assert source_path(layer).read_bytes() == before
    assert not (STORAGE_DIR / 'expired-sources' / key).exists()
    with SessionLocal() as session:
        assert session.get(RenderJob, key).source_state == 'retained'


@pytest.mark.parametrize('expired', [False, True])
def test_recipe_upgrade_uses_snapshot_and_preserves_original_retention(client, expired):
    from datetime import datetime
    layer = upload(client, json.dumps(GEO).encode()).json()
    asset_id, version = layer['asset_id'], layer['asset_version']
    legacy_key = hashlib.sha256(f'{asset_id}:{version}:generic:geojson-v1'.encode()).hexdigest()
    first_ready = datetime(2026, 1, 1)
    expiry = first_ready + timedelta(days=7)
    with SessionLocal() as session:
        session.execute(delete(RenderJob))
        session.add(RenderJob(key=legacy_key, asset_id=asset_id, version=version, profile='generic',
            recipe='geojson-v1', status='succeeded', created_at=first_ready, updated_at=first_ready,
            ready_at=first_ready, source_expires_at=expiry, source_state='expired' if expired else 'retained'))
        session.commit()
        if expired:
            source_path(layer).unlink()
        assert rendering.describe(session, asset_id, version) is None, 'old display recipe must not be exposed'
        job = rendering.enqueue(session, asset_id, version)
        session.commit()
        assert job.status == 'queued' and job.key != legacy_key
        assert job.ready_at == first_ready and job.source_expires_at == expiry
        assert job.source_state == ('expired' if expired else 'retained')
        from app.geojson_snapshot import iter_export
        assert json.loads(''.join(iter_export(asset_id, version))) == GEO
    assert client.get(f'/api/render-files/{legacy_key}/map.pmtiles').status_code == 404


def test_scan_cancels_obsolete_active_recipe_without_reusing_it(client):
    from datetime import datetime
    layer = upload(client, json.dumps(GEO).encode()).json()
    with SessionLocal() as session:
        session.execute(delete(RenderJob))
        key = hashlib.sha256(f"{layer['asset_id']}:{layer['asset_version']}:generic:geojson-v1".encode()).hexdigest()
        old = RenderJob(key=key, asset_id=layer['asset_id'], version=layer['asset_version'],
            profile='generic', recipe='geojson-v1', status='running', created_at=datetime.now(), updated_at=datetime.now())
        session.add(old)
        session.commit()
        rendering.scan(session)
        assert session.get(RenderJob, old.key).status == 'cancelled'
        current = rendering.describe(session, layer['asset_id'], layer['asset_version'])
        assert current and current['status'] == 'queued' and current['recipe'] != 'geojson-v1'

import hashlib
import json
import math
import os
import random
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient
from shapely.geometry import shape
from shapely.ops import transform, unary_union

from tile_service.service import Settings, Store, Worker, create_app
from tile_service.tests.test_service import feature


class HttpTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('tippecanoe'), 'requires fixed Felt tippecanoe')
    def test_oversized_road_tile_fails_instead_of_reducing_fidelity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = Store(root)
            job = store.submit(dict(key='oversized', source_url='http://localhost/internal/render-source/a/1.0.0',
                                    asset_id='a', version='1.0.0', profile='roads', source_mode='push'))
            directory = root / job['id']
            directory.mkdir()
            rng = random.Random(42)
            alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            items = [feature(str(index), [[113, 23], [113.001, 23.001]],
                             name=''.join(rng.choices(alphabet, k=900))) for index in range(4000)]
            (directory / 'source.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': items}))
            (directory / 'source-meta.json').write_text(json.dumps(['e' * 64, len(items)]))
            worker = Worker(Settings(root, 'a' * 32, 'http://localhost'), store)
            with self.assertRaisesRegex(ValueError, r'(?s)Tippecanoe failed.*2097152'):
                worker.run(job, directory)
            self.assertNotEqual(store.get(job['id'])['status'], 'succeeded')
            self.assertFalse((directory / 'artifact.zip').exists())

    @unittest.skipUnless(shutil.which('tippecanoe'), 'requires fixed Felt tippecanoe')
    def test_real_pipeline_preserves_road_turns_at_low_and_maximum_zoom(self):
        radius = 6378137
        origin_x = math.radians(113) * radius
        origin_y = math.log(math.tan(math.pi / 4 + math.radians(23) / 2)) * radius

        def geographic(x, y):
            return [math.degrees((origin_x + x) / radius),
                    math.degrees(2 * math.atan(math.exp((origin_y + y) / radius)) - math.pi / 2)]

        def projected(x, y, z=None):
            return (math.radians(x) * radius,
                    math.log(math.tan(math.pi / 4 + math.radians(y) / 2)) * radius)

        # Curves, S turns, a closed ring, and a winding ramp all fit below a
        # coarse low-zoom simplification tolerance while retaining visible turns.
        paths = [
            [(i * 3, 80 * math.sin(i / 20)) for i in range(241)],
            [(i * 3, 350 + 35 * math.sin(i / 7)) for i in range(241)],
            [(1100 + 90 * math.cos(i * math.pi / 90), 90 * math.sin(i * math.pi / 90)) for i in range(181)],
            [(1000 + i * 2, 350 + i / 3 + 25 * math.sin(i / 5)) for i in range(241)],
        ]
        items = [feature(str(index), [geographic(x, y) for x, y in points], name=str(index))
                 for index, points in enumerate(paths)]
        # Close with exactly the same source endpoint.
        items[2]['geometry']['coordinates'][-1] = items[2]['geometry']['coordinates'][0]
        for profile in ('roads', 'generic'):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                store = Store(root)
                payload = dict(key='fidelity', source_url='http://localhost/internal/render-source/a/1.0.0',
                               asset_id='a', version='1.0.0', profile=profile, recipe='geojson-v2', source_mode='push')
                job = store.submit(payload)
                directory = root / job['id']
                directory.mkdir()
                (directory / 'source.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': items}))
                (directory / 'source-meta.json').write_text(json.dumps(['f' * 64, len(items)]))
                worker = Worker(Settings(root, 'a' * 32, 'http://localhost'), store)
                worker.run(job, directory)
                self.assertEqual(store.get(job['id'])['status'], 'succeeded')
                manifest = json.loads((directory / 'manifest.json').read_text())
                self.assertEqual(manifest['road_sources'], 'road_sources.jsonl')
                with zipfile.ZipFile(directory / 'artifact.zip') as bundle:
                    groups = [json.loads(line) for line in bundle.read('road_sources.jsonl').splitlines()]
                self.assertEqual({source for group in groups for source in group['source_object_ids']}, {'0', '1', '2', '3'})
                for zoom, meters_per_pixel in ((10, 10), (12, 2), (16, 2)):
                    decoded = subprocess.check_output(['tippecanoe-decode', '-c', f'-Z{zoom}', f'-z{zoom}',
                                                       str(directory / 'map.pmtiles')], text=True)
                    parts = {}
                    for line in decoded.splitlines():
                        item = json.loads(line)
                        parts.setdefault(item['properties']['object_id'], []).append(transform(projected, shape(item['geometry'])))
                    self.assertEqual(set(parts), {'0', '1', '2', '3'})
                    for item in items:
                        source = transform(projected, shape(item['geometry']))
                        actual = unary_union(parts[item['__object']['object_id']])
                        error = source.hausdorff_distance(actual) * math.cos(math.radians(23))
                        self.assertLessEqual(error / meters_per_pixel, 1, (profile, zoom, item['__object']['object_id'], error))
                self.assertTrue(manifest['contains_roads'])
                self.assertEqual(manifest['recipe'], 'geojson-v2')

    def test_push_source_waits_for_complete_stream_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = create_app(Settings(root, 'a' * 32, 'http://localhost:8000'), start_worker=False)
            with TestClient(app) as client:
                client.headers['Authorization'] = 'Bearer ' + 'a' * 32
                payload = dict(key='push', source_url='http://localhost:8000/internal/render-source/a/1.0.0',
                               asset_id='a', version='1.0.0', profile='generic', source_mode='push')
                job = client.post('/internal/jobs', json=payload).json()
                self.assertTrue(job['needs_source'])
                self.assertIsNone(app.state.store.claim())
                headers = {'X-Snapshot-Sha256': 'e' * 64, 'X-Feature-Count': '1'}
                result = client.put(f"/internal/jobs/{job['id']}/source", content=b'{"type":"FeatureCollection","features":[]}', headers=headers)
                self.assertEqual(result.status_code, 200)
                self.assertFalse(result.json()['needs_source'])
                app.state.store.recover()
                self.assertTrue((root / job['id'] / 'source.geojson').exists())
                self.assertEqual(app.state.store.claim()['id'], job['id'])
                self.assertEqual(client.put(f"/internal/jobs/{job['id']}/source", content=b'ignored', headers=headers).status_code, 200)

    @unittest.skipUnless(shutil.which('tippecanoe'), 'requires fixed Felt tippecanoe')
    def test_maximum_zoom_identity_loss_fails_before_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = Store(root)
            job = store.submit(dict(key='audit', source_url='http://localhost/internal/render-source/a/1.0.0',
                                    asset_id='a', version='1.0.0', profile='generic'))
            store.claim()
            db = sqlite3.connect(root / 'spool.sqlite3')
            db.execute('CREATE TABLE expected(id TEXT PRIMARY KEY,idx INTEGER,group_id TEXT,seen INTEGER DEFAULT 0)')
            db.executemany('INSERT INTO expected(id,idx) VALUES(?,?)', [('kept', 0), ('missing', 1)])
            db.commit()
            db.close()
            source = root / 'one.json'
            source.write_text(json.dumps({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [113, 23]},
                                          'properties': {'object_id': 'kept', 'feature_index': 0}}), encoding='utf8')
            archive = root / 'one.pmtiles'
            subprocess.run(['tippecanoe', '-q', '-z16', '-Z16', '-r1', '-l', 'data', '-o', str(archive), str(source)], check=True)
            worker = Worker(Settings(root, 'a' * 32, 'http://localhost'), store)
            with self.assertRaisesRegex(ValueError, 'missing'):
                worker.audit_archive(archive, root, job['id'])
            self.assertNotEqual(store.get(job['id'])['status'], 'succeeded')

    def test_auth_key_conflict_cancel_and_explicit_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Settings(Path(temp), 'a' * 32, 'http://localhost:8000')
            app = create_app(config, start_worker=False)
            with TestClient(app) as client:
                payload = dict(key='x', source_url='http://localhost:8000/internal/render-source/a/1.0.0',
                               asset_id='a', version='1.0.0', profile='roads')
                self.assertEqual(client.post('/internal/jobs', json=payload).status_code, 401)
                client.headers['Authorization'] = 'Bearer ' + config.token
                job = client.post('/internal/jobs', json=payload).json()
                self.assertEqual(job['id'], client.post('/internal/jobs', json=payload).json()['id'])
                conflict = client.post('/internal/jobs', json={**payload, 'profile': 'poi'})
                self.assertEqual(conflict.status_code, 409)
                self.assertEqual(client.post(f"/internal/jobs/{job['id']}/cancel").json()['status'], 'cancelled')
                self.assertEqual(client.post('/internal/jobs', json=payload).json()['id'], job['id'])
                retried = client.post('/internal/jobs', json={**payload, 'retry': True}).json()
                self.assertNotEqual(retried['id'], job['id'])

    @unittest.skipUnless(shutil.which('tippecanoe'), 'requires fixed Felt tippecanoe')
    def test_real_http_download_tiling_bundle_acknowledgement(self):
        body = json.dumps({'type': 'FeatureCollection', 'features': [
            feature('0', [[113, 23], [113.001, 23]]),
            feature('1', [[113.001, 23], [113.002, 23]]),
        ]}).encode()
        token = 'a' * 32

        class Source(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.headers.get('Authorization') != 'Bearer ' + token:
                    self.send_error(401)
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('X-Snapshot-Sha256', 'f' * 64)
                self.send_header('X-Feature-Count', '2')
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Source)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                origin = f'http://127.0.0.1:{server.server_port}'
                config = Settings(Path(temp), token, origin)
                app = create_app(config)
                with TestClient(app) as client:
                    client.headers['Authorization'] = 'Bearer ' + token
                    job = client.post('/internal/jobs', json=dict(key='e2e', source_url=origin + '/internal/render-source/a/1.0.0',
                                                                profile='roads', asset_id='a', version='1.0.0')).json()
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        job = client.get('/internal/jobs/' + job['id']).json()
                        if job['status'] in ('succeeded', 'failed') and app.state.worker.current is None:
                            break
                        time.sleep(0.05)
                    self.assertEqual(job['status'], 'succeeded', job)
                    result = client.get(f"/internal/jobs/{job['id']}/artifact")
                    self.assertEqual(hashlib.sha256(result.content).hexdigest(), job['artifact_sha256'])
                    directory = Path(temp) / job['id']
                    self.assertEqual([item.name for item in directory.iterdir()], ['artifact.zip'])
                    with zipfile.ZipFile(directory / 'artifact.zip') as bundle:
                        manifest = json.loads(bundle.read('manifest.json'))
                        self.assertEqual(manifest['source_snapshot_sha256'], 'f' * 64)
                        self.assertEqual(manifest['feature_count'], 2)
                        self.assertEqual(manifest['display_feature_count'], 1)
                        self.assertEqual(bundle.read('map.pmtiles')[:8], b'PMTiles\x03')
                        mapping = json.loads(bundle.read('road_sources.jsonl'))
                        self.assertEqual(mapping['source_object_ids'], ['0', '1'])
                    self.assertEqual(client.delete(f"/internal/jobs/{job['id']}/artifact").status_code, 200)
                    self.assertFalse(directory.exists())
                    self.assertEqual(client.get(f"/internal/jobs/{job['id']}/artifact").status_code, 409)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()

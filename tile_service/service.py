"""One-process serial tiling worker. All mutable files live in the Linux data root."""
import hashlib
import hmac
import json
import math
import os
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
import zipfile
from collections import Counter
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import Depends, FastAPI, Header, HTTPException, Request as WebRequest
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from shapely import get_coordinates, line_merge, make_valid, remove_repeated_points, set_precision
from shapely.geometry import MultiLineString, mapping, shape

from app.geojson_stream import features
from app.poi_style import poi_style
from app.road_style import RANK, classification, road_groups, signature

TOOL_VERSION = '2.79.0'
RECIPE = 'geojson-v2'
MAX_ZOOM = 16


@dataclass
class Settings:
    root: Path
    token: str
    backend_origin: str
    tippecanoe: str = 'tippecanoe'

    @classmethod
    def from_env(cls):
        token = os.environ.get('CITY_TILE_TOKEN', '')
        if len(token) < 24:
            raise RuntimeError('CITY_TILE_TOKEN must contain at least 24 characters')
        return cls(Path(os.environ.get('CITY_TILE_DATA', str(Path.home() / '.local/share/city-tile'))),
                   token, os.environ.get('CITY_TILE_BACKEND_ORIGIN', 'http://127.0.0.1:18743').rstrip('/'),
                   os.environ.get('CITY_TILE_TIPPECANOE', 'tippecanoe'))


def check_source_url(config, url, asset_id, version):
    target, origin = urlsplit(url), urlsplit(config.backend_origin)
    expected = f'/internal/render-source/{quote(asset_id, safe="")}/{quote(str(version), safe="")}'
    if (target.scheme not in ('http', 'https') or target.scheme != origin.scheme
            or target.netloc != origin.netloc or target.username or target.password
            or target.path != expected or target.query or target.fragment):
        raise ValueError('Source URL must be the configured backend version export endpoint')


class JobRequest(BaseModel):
    key: str = Field(min_length=1, max_length=256)
    source_url: str
    source_mode: str = 'pull'
    profile: str
    asset_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=32)
    recipe: str = RECIPE
    retry: bool = False


class Store:
    def __init__(self, root):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'jobs.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, key TEXT NOT NULL, payload TEXT NOT NULL,
                  status TEXT NOT NULL, stage TEXT NOT NULL, error TEXT,
                  retries INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL,
                  artifact_sha256 TEXT, artifact_bytes INTEGER, acknowledged INTEGER NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS active_key ON jobs(key)
                  WHERE status IN ('queued','running','succeeded');
            ''')
            if 'source_ready' not in {row[1] for row in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN source_ready INTEGER NOT NULL DEFAULT 1')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def submit(self, payload):
        payload = dict(payload)
        retry = payload.pop('retry', False)
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE key=? AND status IN ('queued','running','succeeded')", (payload['key'],)).fetchone()
            if row:
                if row['payload'] != encoded:
                    raise ValueError('Idempotency key already belongs to a different request')
                if retry and row['status'] == 'succeeded' and row['acknowledged']:
                    db.execute("UPDATE jobs SET status='failed',stage='artifact-acknowledged',error='Acknowledged artifact requested again' WHERE id=?", (row['id'],))
                else:
                    return dict(row)
            previous = db.execute('SELECT * FROM jobs WHERE key=? ORDER BY created DESC LIMIT 1', (payload['key'],)).fetchone()
            if previous and not retry:
                return dict(previous)
            identity = uuid.uuid4().hex
            push = payload.get('source_mode') == 'push'
            db.execute('INSERT INTO jobs(id,key,payload,status,stage,created,source_ready) VALUES(?,?,?,?,?,?,?)',
                       (identity, payload['key'], encoded, 'queued', 'waiting-source' if push else 'queued', time.time(), 0 if push else 1))
        return self.get(identity)

    def get(self, identity):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identity,)).fetchone()
            return dict(row) if row else None

    def update(self, identity, **values):
        with self.connect() as db:
            db.execute('UPDATE jobs SET ' + ','.join(f'{key}=?' for key in values) + ' WHERE id=?',
                       (*values.values(), identity))

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE status='queued' AND source_ready=1 ORDER BY created LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running', stage='download' WHERE id=?", (row['id'],))
                return dict(row)

    def recover(self):
        with self.connect() as db:
            for row in db.execute("SELECT id,retries FROM jobs WHERE status='running'").fetchall():
                status = 'queued' if row['retries'] == 0 else 'failed'
                db.execute('UPDATE jobs SET status=?,stage=?,retries=retries+1,error=? WHERE id=?',
                           (status, status, 'Worker interrupted twice' if status == 'failed' else None, row['id']))
            retained = {row['id'] for row in db.execute("SELECT id FROM jobs WHERE status='succeeded' AND acknowledged=0")}
            waiting = set()
            for row in db.execute("SELECT id,payload,source_ready FROM jobs WHERE status='queued'").fetchall():
                if json.loads(row['payload']).get('source_mode') == 'push':
                    directory = self.root / row['id']
                    ready = int((directory / 'source.geojson').is_file() and (directory / 'source-meta.json').is_file())
                    db.execute('UPDATE jobs SET source_ready=?,stage=? WHERE id=?',
                               (ready, 'queued' if ready else 'waiting-source', row['id']))
                    if ready:
                        waiting.add(row['id'])
            for identity in tuple(retained):
                if not (self.root / identity / 'artifact.zip').is_file():
                    db.execute("UPDATE jobs SET status='failed',stage='failed',error='Artifact missing after restart' WHERE id=?", (identity,))
                    retained.remove(identity)
        for directory in self.root.iterdir():
            if directory.is_dir() and len(directory.name) == 32:
                if directory.name in retained or directory.name in waiting:
                    for item in directory.iterdir():
                        allowed = {'artifact.zip'} if directory.name in retained else {'source.geojson', 'source-meta.json'}
                        if item.name not in allowed:
                            if item.is_dir():
                                shutil.rmtree(item)
                            else:
                                item.unlink()
                else:
                    shutil.rmtree(directory)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def source_metadata(headers):
    snapshot_sha256 = headers.get('X-Snapshot-Sha256', '')
    feature_count = int(headers.get('X-Feature-Count', '-1'))
    if (len(snapshot_sha256) != 64 or any(character not in '0123456789abcdef' for character in snapshot_sha256)
            or feature_count < 0):
        raise ValueError('Source is missing canonical snapshot hash/count headers')
    return snapshot_sha256, feature_count


def workspace_bytes(directory):
    total = 0
    for path in directory.rglob('*'):
        try:
            if path.is_file():
                total += path.stat().st_size
        except FileNotFoundError:
            # Tippecanoe unlinks transient runs while the sampler walks them.
            continue
    return total


def geometry_for_display(feature):
    identity = feature['__object']['object_id']
    try:
        geometry = shape(feature['geometry'])
        family = geometry.geom_type.replace('Multi', '')
        if family not in ('Point', 'LineString', 'Polygon') or geometry.is_empty:
            raise ValueError('unsupported or empty geometry')
        before = len(get_coordinates(geometry))
        if not geometry.is_valid:
            geometry = make_valid(geometry)
        geometry = remove_repeated_points(set_precision(geometry, 0.000001))
        if (geometry.is_empty or not geometry.is_valid
                or geometry.geom_type.replace('Multi', '') != family):
            raise ValueError('geometry collapsed or changed dimensional family')
        bounds = geometry.bounds
        if (not all(math.isfinite(value) for value in bounds) or bounds[0] < -180 or bounds[2] > 180
                or bounds[1] < -85.05112878 or bounds[3] > 85.05112878):
            raise ValueError('coordinates outside WGS84 Web Mercator coverage')
        return geometry, before
    except Exception as error:
        raise ValueError(f'Object {identity}: {error}') from error


def display_properties(feature, profile):
    original = feature.get('properties') or {}
    whitelist = ('name', 'name:zh', '名称', 'ref', 'highway', 'fclass', 'bridge', 'tunnel', 'layer', 'oneway',
                 'category', '类别', 'amenity', 'shop', 'tourism', 'railway', 'aeroway', 'leisure', 'historic',
                 'weight', 'color', 'fill', 'fill-opacity', 'stroke', 'stroke-opacity', 'stroke-width',
                 'marker-color', 'marker-size', 'marker-symbol')
    props = {key: original[key] for key in whitelist if key in original and isinstance(original[key], (str, int, float, bool))}
    props.update(object_id=feature['__object']['object_id'], feature_index=feature['__object']['feature_index'])
    family = (feature.get('geometry') or {}).get('type', '').replace('Multi', '')
    explicit_road = 'highway' in original or 'fclass' in original and classification(original) in RANK
    if profile == 'roads' or profile == 'generic' and family != 'Point' and explicit_road:
        props.update(road_class=classification(original), road_rank=RANK.get(classification(original), 99))
        props['road_renderable'] = family == 'LineString'
        props['name'] = original.get('name') or original.get('名称') or ''
    if profile == 'poi':
        style = poi_style(original, 0)
        props.update(poi_category=style['category'], priority=style['priority'], name=style['name'])
        props['background_eligible'] = bool(style['name'])
        props['max_scale'] = next((scale for scale in (float('inf'), 20, 5, 1)
                                   if poi_style(original, scale)['eligible']), 0)
        if props['max_scale'] == float('inf'):
            props['max_scale'] = -1
        for key in ('importance', 'weight', 'priority'):
            try:
                weight = float(original.get(key))
                if math.isfinite(weight):
                    props['weight'] = weight
                    break
            except (ValueError, TypeError):
                continue
    return props


def prepare(source, directory, profile, cancelled):
    """Spool geometries to SQLite; only road endpoint metadata stays in memory."""
    spool = directory / 'spool.sqlite3'
    db = sqlite3.connect(spool)
    db.execute('CREATE TABLE features(id TEXT PRIMARY KEY, idx INTEGER UNIQUE, feature TEXT NOT NULL)')
    db.execute('CREATE TABLE expected(id TEXT PRIMARY KEY, idx INTEGER, group_id TEXT, seen INTEGER DEFAULT 0)')
    segments, degrees = {}, Counter()
    count = before_vertices = after_vertices = source_props = render_props = 0
    contains_roads = profile == 'roads'
    bounds = [180., 90., -180., -90.]
    identities = hashlib.sha256()
    try:
        for feature in features(source, cancelled):
            cancelled()
            meta = feature.get('__object') or {}
            identity, index = meta.get('object_id'), meta.get('feature_index')
            if not isinstance(identity, str) or not identity or type(index) is not int or index < 0:
                raise ValueError('Every feature requires stable __object identity and original index')
            geometry, before = geometry_for_display(feature)
            props = display_properties(feature, profile)
            contains_roads = contains_roads or 'road_rank' in props
            rendered = {'type': 'Feature', 'properties': props, 'geometry': mapping(geometry)}
            db.execute('INSERT INTO features VALUES(?,?,?)', (identity, index, json.dumps(rendered, ensure_ascii=False, allow_nan=False)))
            if count % 1000 == 0:
                db.commit()
            if profile in ('roads', 'generic') and geometry.geom_type in ('LineString', 'MultiLineString'):
                # Original endpoints avoid introducing topology through precision snapping.
                coords = feature['geometry']['coordinates']
                lines = [coords] if geometry.geom_type == 'LineString' else coords
                for line in lines:
                    degrees.update((tuple(line[0][:2]), tuple(line[-1][:2])))
                if geometry.geom_type == 'LineString' and 'road_rank' in props:
                    endpoints = (tuple(coords[0][:2]), tuple(coords[-1][:2]))
                    key_feature = {'id': identity, 'properties': feature.get('properties') or {}}
                    segments[identity] = (index, signature(key_feature), endpoints)
            box = geometry.bounds
            bounds = [min(bounds[0], box[0]), min(bounds[1], box[1]), max(bounds[2], box[2]), max(bounds[3], box[3])]
            count += 1
            before_vertices += before
            after_vertices += len(get_coordinates(geometry))
            source_props += len(json.dumps(feature.get('properties') or {}, ensure_ascii=False).encode('utf8'))
            render_props += len(json.dumps(props, ensure_ascii=False).encode('utf8'))
            identities.update(json.dumps([identity, index], separators=(',', ':'), ensure_ascii=False).encode('utf8') + b'\n')
        db.commit()
        if not count:
            raise ValueError('No renderable features')
        groups = road_groups(segments, degrees)
        emitted = set()
        display_count = 0
        with (directory / 'render.jsonl').open('w', encoding='utf8') as output, (directory / 'road_sources.jsonl').open('w', encoding='utf8') as sources:
            def emit(item):
                nonlocal display_count
                # Road density is handled by scale filtering, never random drop.
                if profile == 'roads' or profile == 'generic' and 'road_rank' in item['properties']:
                    # Conservative at the Web Mercator latitude limit. The viewer
                    # applies its exact local meters-per-pixel threshold as well.
                    rank = item['properties']['road_rank']
                    item['tippecanoe'] = {'minzoom': (0, 9, 11, 13)[rank] if rank <= 3 else 0}
                elif profile == 'poi':
                    scale = item['properties']['max_scale']
                    minimum = MAX_ZOOM if not item['properties']['background_eligible'] else {-1: 0, 20: 9, 5: 11, 1: 13}.get(scale, MAX_ZOOM)
                    item['tippecanoe'] = {'minzoom': minimum}
                output.write(json.dumps(item, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n')
                props = item['properties']
                db.execute('INSERT INTO expected(id,idx,group_id) VALUES(?,?,?)',
                           (props['object_id'], props['feature_index'], props.get('display_group_id')))
                display_count += 1
            for group in groups:
                cancelled()
                encoded_size = sum(db.execute('SELECT length(feature) FROM features WHERE id=?', (identity,)).fetchone()[0] for identity in group)
                if encoded_size > 64 * 1024 * 1024:
                    raise ValueError(f'Road chain {group[0]} exceeds 64 MiB bounded merge limit')
                lines, first = [], None
                for identity in group:
                    item = json.loads(db.execute('SELECT feature FROM features WHERE id=?', (identity,)).fetchone()[0])
                    first = first or item
                    lines.append(shape(item['geometry']))
                merged = line_merge(MultiLineString(lines))
                group_id = 'road:' + hashlib.sha256(json.dumps(group, separators=(',', ':')).encode()).hexdigest()[:24]
                first['geometry'] = mapping(merged)
                first['properties']['display_group_id'] = group_id
                sources.write(json.dumps({'group_id': group_id, 'source_object_ids': group}, separators=(',', ':')) + '\n')
                emit(first)
                emitted.update(group)
            for identity, encoded in db.execute('SELECT id,feature FROM features ORDER BY idx'):
                cancelled()
                if identity not in emitted:
                    emit(json.loads(encoded))
        db.commit()
        return {'feature_count': count, 'display_feature_count': display_count, 'bounds': bounds,
                'contains_roads': contains_roads,
                'identity_sha256': identities.hexdigest(), 'vertices_before': before_vertices,
                'vertices_after': after_vertices, 'property_bytes_before': source_props,
                'property_bytes_after': render_props}
    finally:
        db.close()


class Cancelled(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Backend source redirects are prohibited')


class Worker:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.stop = threading.Event()
        self.process = None
        self.current = None
        self.lock = threading.RLock()
        self.checked_at = 0
        self.checked_identity = None
        self.peak_bytes = 0
        self.thread = threading.Thread(target=self.loop, daemon=True, name='serial-tiler')

    def check(self, identity, *, force=False):
        if self.stop.is_set():
            raise Cancelled()
        clock = time.monotonic()
        # The streaming parser checks every JSON token; do not open SQLite for
        # every coordinate. Cancellation latency remains bounded at 100 ms.
        if not force and self.checked_identity == identity and clock - self.checked_at < 0.1:
            return
        self.checked_identity, self.checked_at = identity, clock
        if self.store.get(identity)['status'] == 'cancelled':
            raise Cancelled()

    def terminate(self):
        with self.lock:
            process = self.process
            if process and process.poll() is None:
                try:
                    if os.name == 'posix':
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == 'posix':
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait()
                except ProcessLookupError:
                    pass

    def loop(self):
        while not self.stop.is_set():
            job = self.store.claim()
            if not job:
                self.stop.wait(0.5)
                continue
            identity = job['id']
            self.current = identity
            self.peak_bytes = 0
            directory = self.store.root / identity
            directory.mkdir(exist_ok=True)
            try:
                self.run(job, directory)
            except Cancelled:
                if not self.stop.is_set():
                    self.store.update(identity, status='cancelled', stage='cancelled')
            except Exception as error:
                if self.store.get(identity)['status'] != 'cancelled':
                    self.store.update(identity, status='failed', stage='failed', error=str(error)[-12000:])
            finally:
                self.terminate()
                with self.lock:
                    self.process = None
                    state = self.store.get(identity)
                    keep = state['status'] == 'succeeded' and not state['acknowledged']
                    for path in directory.iterdir():
                        if not (keep and path.name == 'artifact.zip'):
                            if path.is_dir():
                                shutil.rmtree(path)
                            else:
                                path.unlink(missing_ok=True)
                    if not keep:
                        directory.rmdir()
                    self.current = None

    def audit_archive(self, archive, directory, identity):
        """Decode the maximum zoom and compare display identities in bounded memory."""
        decoder = str(Path(self.config.tippecanoe).with_name('tippecanoe-decode'))
        decoded, log = directory / 'decoded.jsonl', directory / 'audit.log'
        with decoded.open('wb') as output, log.open('wb') as errors:
            with self.lock:
                self.check(identity)
                self.process = subprocess.Popen([decoder, '-c', f'-Z{MAX_ZOOM}', f'-z{MAX_ZOOM}', '-l', 'data',
                                                 '-y', 'object_id', '-y', 'feature_index', '-y', 'display_group_id', str(archive)],
                                                stdout=output, stderr=errors, start_new_session=os.name == 'posix')
            while self.process.poll() is None:
                self.check(identity)
                self.peak_bytes = max(self.peak_bytes, workspace_bytes(directory))
                time.sleep(0.25)
        self.check(identity)
        self.peak_bytes = max(self.peak_bytes, workspace_bytes(directory))
        if self.process.returncode:
            raise ValueError('PMTiles maximum-zoom decode failed')
        db = sqlite3.connect(directory / 'spool.sqlite3')
        try:
            with decoded.open(encoding='utf8') as stream:
                for line in stream:
                    self.check(identity)
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    props = item.get('properties') or {}
                    expected = db.execute('SELECT idx,group_id FROM expected WHERE id=?', (props.get('object_id'),)).fetchone()
                    if not expected or (expected[0], expected[1]) != (props.get('feature_index'), props.get('display_group_id')):
                        raise ValueError(f'Unexpected maximum-zoom identity: {props.get("object_id")}')
                    db.execute('UPDATE expected SET seen=1 WHERE id=?', (props['object_id'],))
            missing = db.execute('SELECT id FROM expected WHERE seen=0 LIMIT 1').fetchone()
            if missing:
                raise ValueError(f'Object {missing[0]} disappeared from maximum zoom')
        finally:
            db.close()
        decoded.unlink()

    def run(self, job, directory):
        identity, payload = job['id'], json.loads(job['payload'])
        check = lambda: self.check(identity)
        check_source_url(self.config, payload['source_url'], payload['asset_id'], payload['version'])
        check()
        version = subprocess.check_output([self.config.tippecanoe, '--version'], stderr=subprocess.STDOUT, text=True).strip()
        if version != f'tippecanoe v{TOOL_VERSION}':
            raise ValueError(f'Expected Felt tippecanoe v{TOOL_VERSION}, got {version}')
        source = directory / 'source.geojson'
        if payload.get('source_mode') == 'push':
            snapshot_sha256, feature_count = json.loads((directory / 'source-meta.json').read_text())
        else:
            request = Request(payload['source_url'], headers={'Authorization': 'Bearer ' + self.config.token})
            with build_opener(NoRedirect()).open(request, timeout=30) as response, source.open('wb') as target:
                snapshot_sha256, feature_count = source_metadata(response.headers)
                total = 0
                while chunk := response.read(1024 * 1024):
                    check()
                    total += len(chunk)
                    if total > 4 * 1024**3:
                        raise ValueError('Normalized source exceeds 4 GiB transfer bound')
                    target.write(chunk)
        self.store.update(identity, stage='preprocess')
        stats = prepare(source, directory, payload['profile'], check)
        if stats['feature_count'] != feature_count:
            raise ValueError('Source feature count differs from canonical snapshot')
        source_bytes = source.stat().st_size
        self.peak_bytes = max(self.peak_bytes, workspace_bytes(directory))
        source.unlink()
        self.store.update(identity, stage='tiling')
        archive = directory / 'map.pmtiles'
        geometry_options = (['--no-line-simplification', '--full-detail=12', '--low-detail=12', '--minimum-detail=12']
                            if stats['contains_roads'] else ['--simplify-only-low-zooms'])
        args = [self.config.tippecanoe, '--output', str(archive), '--layer', 'data', '--minimum-zoom', '0',
                '--maximum-zoom', str(MAX_ZOOM), '--drop-rate', '1', '--buffer', '5', '--no-feature-limit',
                '--maximum-tile-bytes', str(2 * 1024 * 1024),
                '--no-tiny-polygon-reduction', *geometry_options, '--detect-shared-borders',
                '--temporary-directory', str(directory), str(directory / 'render.jsonl')]
        log = directory / 'tippecanoe.log'
        with log.open('wb') as output:
            with self.lock:
                check()
                self.process = subprocess.Popen(args, stdout=output, stderr=subprocess.STDOUT, start_new_session=os.name == 'posix')
            while self.process.poll() is None:
                try:
                    check()
                except Cancelled:
                    self.terminate()
                    raise
                self.peak_bytes = max(self.peak_bytes, workspace_bytes(directory))
                time.sleep(0.25)
        check()
        if self.process.returncode:
            with log.open('rb') as output:
                output.seek(max(0, log.stat().st_size - 10000))
                lines = output.read().decode('utf8', errors='replace').replace('\r', '\n').splitlines()
                tail = '\n'.join(line for line in lines if '%' not in line)[-8000:]
            raise ValueError(f'Tippecanoe failed ({self.process.returncode}): {tail}')
        with archive.open('rb') as stream:
            if stream.read(8) != b'PMTiles\x03':
                raise ValueError('Invalid PMTiles v3 output')
        self.store.update(identity, stage='verify-identities')
        self.audit_archive(archive, directory, identity)
        self.store.update(identity, stage='packaging')
        manifest = {**stats, 'asset_id': payload['asset_id'], 'version': payload['version'], 'recipe': payload['recipe'],
                    'profile': payload['profile'], 'source_layer': 'data', 'minzoom': 0, 'maxzoom': MAX_ZOOM,
                    'tool_version': version, 'pmtiles_sha256': digest(archive), 'source_bytes': source_bytes,
                    'source_snapshot_sha256': snapshot_sha256, 'source_feature_count': feature_count,
                    'render_bytes': (directory / 'render.jsonl').stat().st_size, 'pmtiles_bytes': archive.stat().st_size,
                    'peak_workspace_bytes': max(self.peak_bytes, workspace_bytes(directory)),
                    'recipe_options': ['--layer=data', '-Z0', f'-z{MAX_ZOOM}', '-r1', '--buffer=5', '--no-feature-limit', '--maximum-tile-bytes=2097152',
                                       '--no-tiny-polygon-reduction', *geometry_options, '--detect-shared-borders']}
        if payload['profile'] == 'roads' or (directory / 'road_sources.jsonl').stat().st_size:
            manifest['road_sources'] = 'road_sources.jsonl'
        (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf8')
        bundle = directory / 'artifact.zip'
        with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as target:
            target.write(archive, 'map.pmtiles')
            target.write(directory / 'manifest.json', 'manifest.json')
            if manifest.get('road_sources'):
                target.write(directory / 'road_sources.jsonl', 'road_sources.jsonl')
        check()
        # Serialize with cancellation: a cancelled job must never become succeeded.
        with self.lock:
            self.check(identity, force=True)
            self.store.update(identity, status='succeeded', stage='succeeded', artifact_sha256=digest(bundle), artifact_bytes=bundle.stat().st_size)


def public_job(job):
    return {**{key: job[key] for key in ('id', 'status', 'stage', 'artifact_sha256', 'artifact_bytes', 'acknowledged')},
            'error': job['error'] or '',
            'needs_source': job['status'] == 'queued' and job['source_ready'] == 0}


def create_app(config=None, *, start_worker=True):
    config = config or Settings.from_env()
    store = Store(config.root)
    worker = Worker(config, store)

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            store.recover()
            worker.thread.start()
        yield
        if start_worker:
            worker.stop.set()
            worker.terminate()
            worker.thread.join(timeout=35)

    app = FastAPI(lifespan=lifespan)
    app.state.store, app.state.worker = store, worker

    def authorized(authorization: str = Header(default='')):
        if not hmac.compare_digest(authorization, 'Bearer ' + config.token):
            raise HTTPException(401, 'Invalid internal token')

    def find(identity):
        job = store.get(identity)
        if not job:
            raise HTTPException(404, 'Unknown job')
        return job

    @app.get('/health')
    def health():
        return {'status': 'ok', 'worker_alive': worker.thread.is_alive(), 'recipe': RECIPE, 'tool_version': TOOL_VERSION}

    @app.post('/internal/jobs', dependencies=[Depends(authorized)])
    def submit(payload: JobRequest):
        if payload.profile not in ('roads', 'poi', 'generic') or payload.recipe != RECIPE or payload.source_mode not in ('pull', 'push'):
            raise HTTPException(422, 'Unsupported render profile or recipe')
        try:
            check_source_url(config, payload.source_url, payload.asset_id, payload.version)
            return public_job(store.submit(payload.model_dump()))
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.put('/internal/jobs/{identity}/source', dependencies=[Depends(authorized)])
    async def push_source(identity: str, request: WebRequest):
        job = find(identity)
        if json.loads(job['payload']).get('source_mode') != 'push':
            raise HTTPException(409, 'Job uses pull source transport')
        try:
            metadata = source_metadata(request.headers)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM jobs WHERE id=?', (identity,)).fetchone()
            if current['source_ready'] == 1 or current['status'] == 'succeeded':
                return public_job(dict(current))
            if current['source_ready'] == -1:
                raise HTTPException(503, 'Source intake already active; retry later')
            if current['status'] != 'queued':
                raise HTTPException(409, 'Source intake unavailable or already active')
            db.execute('UPDATE jobs SET source_ready=-1 WHERE id=?', (identity,))
        directory = store.root / identity
        directory.mkdir(exist_ok=True)
        incoming = directory / 'incoming.tmp'
        try:
            size = 0
            with incoming.open('wb') as output:
                async for chunk in request.stream():
                    if store.get(identity)['status'] != 'queued':
                        raise HTTPException(409, 'Job was cancelled during source intake')
                    size += len(chunk)
                    if size > 4 * 1024**3:
                        raise HTTPException(413, 'Normalized source exceeds 4 GiB')
                    output.write(chunk)
            with worker.lock:
                if store.get(identity)['status'] != 'queued':
                    raise HTTPException(409, 'Job was cancelled during source intake')
                (directory / 'source-meta.json').write_text(json.dumps(metadata))
                incoming.replace(directory / 'source.geojson')
                store.update(identity, source_ready=1, stage='queued')
            return public_job(find(identity))
        except BaseException:
            incoming.unlink(missing_ok=True)
            store.update(identity, source_ready=0)
            raise

    @app.get('/internal/jobs/{identity}', dependencies=[Depends(authorized)])
    def status(identity: str):
        return public_job(find(identity))

    @app.post('/internal/jobs/{identity}/cancel', dependencies=[Depends(authorized)])
    def cancel(identity: str):
        with worker.lock:
            job = find(identity)
            if job['status'] in ('queued', 'running'):
                store.update(identity, status='cancelled', stage='cancelled')
                if worker.current == identity:
                    worker.terminate()
            return public_job(find(identity))

    @app.get('/internal/jobs/{identity}/artifact', dependencies=[Depends(authorized)])
    def artifact(identity: str):
        job = find(identity)
        path = config.root / identity / 'artifact.zip'
        if job['status'] != 'succeeded' or not path.exists():
            raise HTTPException(409, 'Artifact unavailable or already acknowledged')
        return FileResponse(path, media_type='application/zip', filename='artifact.zip', headers={'ETag': '"' + job['artifact_sha256'] + '"'})

    @app.delete('/internal/jobs/{identity}/artifact', dependencies=[Depends(authorized)])
    def acknowledge(identity: str):
        job = find(identity)
        if job['status'] in ('running', 'queued'):
            raise HTTPException(409, 'Job is still active')
        directory = config.root / identity
        with worker.lock:
            store.update(identity, acknowledged=1)
            # The worker owns its directory until its final cleanup finishes.
            if worker.current != identity and directory.exists():
                shutil.rmtree(directory)
        return public_job(find(identity))

    return app

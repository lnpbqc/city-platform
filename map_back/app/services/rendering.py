"""Durable display jobs; source snapshots remain authoritative after expiry."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from threading import Event, Lock, Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

from sqlalchemy import select, exists, func

from app.database import SessionLocal, STORAGE_DIR
from app.models import Asset, AssetVersion, Layer, ObjectIndex, SpatialObject, TimeSeriesSnapshot
from app.models.render import RenderJob

RECIPE = 'geojson-v2'
RENDER_DIR = STORAGE_DIR / 'renders'
logger = logging.getLogger('city.renders')


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def next_source_check(at):
    local = at + timedelta(hours=8)
    scheduled = local.replace(hour=3, minute=0, second=0, microsecond=0)
    if scheduled <= local:
        scheduled += timedelta(days=1)
    return scheduled - timedelta(hours=8)


def configuration():
    path = STORAGE_DIR / 'tile-service.json'
    values = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return {name: os.environ.get(env, values.get(name, default)) for name, env, default in (
        ('url', 'CITY_TILE_SERVICE_URL', ''), ('token', 'CITY_TILE_TOKEN', ''),
        ('backend', 'CITY_TILE_BACKEND_ORIGIN', 'http://127.0.0.1:8000'))}


def storage_usage():
    from app.database import FILES_DIR, engine
    def size(folder):
        total = 0
        for path in folder.rglob('*') if folder.exists() else ():
            try:
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                pass
        return total
    database = 0
    if engine.dialect.name == 'sqlite' and engine.url.database:
        for suffix in ('', '-wal', '-shm'):
            path = Path(engine.url.database + suffix)
            try:
                database += path.stat().st_size
            except FileNotFoundError:
                pass
    return {'source_bytes': size(FILES_DIR), 'render_bytes': size(RENDER_DIR), 'database_bytes': database,
            'temporary_bytes': size(STORAGE_DIR / 'tmp') + size(STORAGE_DIR / 'expired-sources')}


def remote(method, path, body=None):
    config = configuration()
    request = Request(config['url'].rstrip('/') + path,
        data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={'Authorization': 'Bearer ' + config['token'], 'Content-Type': 'application/json'})
    return urlopen(request, timeout=15)


def push_source(remote_id, asset_id, version):
    from app.services.geojson_snapshot import iter_export, ready_snapshot
    with SessionLocal() as session:
        snapshot = ready_snapshot(session, asset_id, version)
        if not snapshot:
            raise ValueError('切片来源快照不可用')
        checksum, count = snapshot.sha256, snapshot.feature_count
    config = configuration()
    def chunks():
        batch, size = [], 0
        for chunk in iter_export(asset_id, version, identified=True):
            encoded = chunk.encode('utf-8')
            batch.append(encoded)
            size += len(encoded)
            if size >= 1024**2:
                with SessionLocal() as check:
                    status = check.scalar(select(RenderJob.status).where(RenderJob.remote_id == remote_id))
                    if status != 'running':
                        raise InterruptedError('切片输入已取消')
                yield b''.join(batch)
                batch, size = [], 0
        if batch:
            yield b''.join(batch)
    request = Request(config['url'].rstrip('/') + f'/internal/jobs/{remote_id}/source', data=chunks(), method='PUT',
        headers={'Authorization': 'Bearer ' + config['token'], 'Content-Type': 'application/geo+json',
                 'X-Snapshot-Sha256': checksum, 'X-Feature-Count': str(count)})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def profile_for(category):
    return {'道路': 'roads', '线状网络': 'roads', 'POI': 'poi'}.get(category, 'generic')


def eligible(session, asset, version):
    if not asset or asset.type != 'geojson' or asset.source_kind == 'external' or asset.status != 'active':
        return False
    index = session.get(ObjectIndex, (asset.id, version))
    if not index or index.status != 'ready' or session.get(TimeSeriesSnapshot, (asset.id, version)):
        return False
    # Extruded footprints must continue to use the existing terrain placement.
    return not session.scalar(select(SpatialObject.id).where(SpatialObject.asset_id == asset.id,
        SpatialObject.asset_version == version, SpatialObject.height_m > 0,
        func.json_extract(SpatialObject.geometry, '$.type').in_(('Polygon', 'MultiPolygon'))).limit(1))


def enqueue(session, asset_id, version, category=''):
    profile = profile_for(category)
    key = hashlib.sha256(f'{asset_id}:{version}:{profile}:{RECIPE}'.encode()).hexdigest()
    job = session.get(RenderJob, key)
    if job is None:
        asset = session.get(Asset, asset_id)
        if not eligible(session, asset, version):
            return None
        ready_at, source_expires_at = session.execute(select(func.min(RenderJob.ready_at),
            func.min(RenderJob.source_expires_at)).where(RenderJob.asset_id == asset_id,
            RenderJob.version == version)).one()
        job = RenderJob(key=key, asset_id=asset_id, version=version, profile=profile, recipe=RECIPE,
            status='queued', stage='等待切片服务', error='', byte_size=0, attempts=0,
            created_at=now(), updated_at=now(), ready_at=ready_at, source_expires_at=source_expires_at,
            source_state='expired' if expired_source(session, asset_id, version) else 'retained')
        session.add(job)
    return job


def describe(session, asset_id, version, category=None):
    statement = select(RenderJob).where(RenderJob.asset_id == asset_id, RenderJob.version == version,
        RenderJob.recipe == RECIPE)
    if category is not None:
        statement = statement.where(RenderJob.profile == profile_for(category))
    job = session.scalar(statement.order_by(RenderJob.ready_at.desc(), RenderJob.created_at.desc()).limit(1))
    if not job:
        return None
    return {'key': job.key, 'status': job.status, 'stage': job.stage, 'error': job.error,
        'profile': job.profile, 'recipe': job.recipe, 'manifest': job.manifest,
        'url': f'/api/render-files/{job.key}/map.pmtiles?v={job.sha256}' if job.status == 'succeeded' else None,
        'byte_size': job.byte_size, 'source_state': job.source_state,
        'source_expires_at': job.source_expires_at.replace(tzinfo=timezone.utc).isoformat() if job.source_expires_at else None}


def expired_source(session, asset_id, version):
    return session.scalar(select(RenderJob.key).where(RenderJob.asset_id == asset_id,
        RenderJob.version == version, RenderJob.source_state == 'expired').limit(1)) is not None


def scan(session):
    from app.services.assets import lock_catalog
    lock_catalog(session)
    for job in session.scalars(select(RenderJob).where(RenderJob.recipe != RECIPE,
        RenderJob.status.in_(('queued', 'running')))):
        job.status, job.stage, job.updated_at = 'cancelled', '制图规则已更新，使用新版任务', now()
    for asset, version in session.execute(select(Asset, AssetVersion).join(AssetVersion, AssetVersion.asset_id == Asset.id)
                                         .where(Asset.type == 'geojson', Asset.status == 'active')):
        categories = list(session.scalars(select(Layer.category).where(Layer.asset_id == asset.id,
            Layer.asset_version == version.version).order_by(Layer.map_attached.desc())))
        if not categories:
            from app.services.builtin_assets import BUILTIN_LAYERS, CAMPUS_KEYS, builtin_asset_id
            categories = [spec['category'] for campus in CAMPUS_KEYS for spec in BUILTIN_LAYERS
                          if builtin_asset_id(campus, spec['id']) == asset.id] or ['']
        for category in dict.fromkeys(categories):
            enqueue(session, asset.id, version.version, category)
    session.commit()


def validate_bundle(path, job, destination):
    """Extract only bounded, named derivatives from a service response."""
    with ZipFile(path) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or not {'map.pmtiles', 'manifest.json'} <= set(names):
            raise ValueError('切片产物缺少归档或清单')
        if set(names) - {'map.pmtiles', 'manifest.json', 'road_sources.jsonl'}:
            raise ValueError('切片产物包含未声明文件')
        if sum(item.file_size for item in bundle.infolist()) > 16 * 1024**3:
            raise ValueError('切片产物超过 16 GiB 工作空间预算')
        for info in bundle.infolist():
            if info.is_dir() or info.filename == 'manifest.json' and info.file_size > 1024**2:
                raise ValueError('切片清单过大或包含目录')
            with bundle.open(info) as source, (destination / info.filename).open('wb') as output:
                shutil.copyfileobj(source, output, 1024**2)
    manifest = json.loads((destination / 'manifest.json').read_text(encoding='utf-8'))
    if any(manifest.get(name) != getattr(job, name) for name in ('asset_id', 'version', 'recipe', 'profile')):
        raise ValueError('切片产物资产版本不匹配')
    from app.services.geojson_snapshot import ready_snapshot
    with SessionLocal() as lookup:
        snapshot = ready_snapshot(lookup, job.asset_id, job.version)
        if (not snapshot or manifest.get('source_snapshot_sha256') != snapshot.sha256
                or manifest.get('source_feature_count') != snapshot.feature_count):
            raise ValueError('切片产物完整数据校验不匹配')
    if manifest.get('source_layer') != 'data' or not (0 <= manifest.get('minzoom', -1) <= manifest.get('maxzoom', 99) <= 18):
        raise ValueError('切片图层名或缩放范围错误')
    from app.schemas.common import Bounds
    Bounds.model_validate(dict(zip(('west', 'south', 'east', 'north'), manifest['bounds'])))
    target = destination / 'map.pmtiles'
    with target.open('rb') as stream:
        header = stream.read(127)
        stream.seek(0)
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    if len(header) != 127 or header[:8] != b'PMTiles\x03' or header[99] != 1:
        raise ValueError('切片归档不是 PMTiles v3 MVT')
    if checksum != manifest.get('pmtiles_sha256'):
        raise ValueError('切片归档摘要不匹配')
    return manifest, checksum, sum(item.stat().st_size for item in destination.iterdir())


def publish(key, bundle):
    from app.services.assets import lock_catalog
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='publish-', dir=RENDER_DIR))
    target = RENDER_DIR / key
    previous = RENDER_DIR / (key + '.previous')
    moved = False
    backed_up = False
    committed = False
    try:
        with SessionLocal() as session:
            job = session.get(RenderJob, key)
            if not job or job.status not in ('running', 'queued'):
                return
            manifest, checksum, size = validate_bundle(bundle, job, temporary)
            session.rollback()
            lock_catalog(session)
            job = session.get(RenderJob, key)
            if not job:
                return
            asset = session.get(Asset, job.asset_id)
            if job.status not in ('running', 'queued') or not eligible(session, asset, job.version) or job.recipe != RECIPE:
                return
            if target.exists():
                if previous.exists():
                    shutil.rmtree(previous)
                target.rename(previous)
                backed_up = True
            temporary.rename(target)
            moved = True
            job.manifest, job.sha256, job.byte_size = manifest, checksum, size
            job.status, job.stage, job.error = 'succeeded', '显示瓦片已就绪', ''
            job.ready_at = job.ready_at or now()
            if asset.source_kind == 'upload' and not asset.protected:
                job.source_expires_at = job.source_expires_at or job.ready_at + timedelta(days=7)
            job.updated_at = now()
            session.commit()
            committed = True
    except Exception:
        if moved and target.exists():
            shutil.rmtree(target)
        if backed_up and previous.exists():
            previous.rename(target)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        if committed and previous.exists():
            try:
                shutil.rmtree(previous)
            except OSError:
                logger.warning('旧显示产物仍在读取，下次启动时清理 %s', key)


def cancel_asset(session, asset_id):
    for job in session.scalars(select(RenderJob).where(RenderJob.asset_id == asset_id)):
        job.status, job.stage, job.updated_at = 'cancelled', '资产已删除，清理切片任务', now()
        folder = RENDER_DIR / job.key
        if folder.exists():
            shutil.rmtree(folder)


def expire_sources(at=None):
    from app.services.assets import _deletion_lock, lock_catalog, local_parts
    from app.database import FILES_DIR
    from app.services.geojson_snapshot import ready_snapshot
    at = at or now()
    with _deletion_lock, SessionLocal() as session:
        lock_catalog(session)
        jobs = list(session.scalars(select(RenderJob).where(RenderJob.status == 'succeeded',
            RenderJob.source_expires_at <= at, RenderJob.source_state != 'expired')))
        for job in jobs:
            session.rollback()
            lock_catalog(session)
            session.refresh(job)
            if job.source_state == 'expired' or job.status != 'succeeded':
                continue
            asset = session.get(Asset, job.asset_id)
            version = session.get(AssetVersion, (job.asset_id, job.version))
            if not version or not eligible(session, asset, job.version) or asset.protected or asset.source_kind != 'upload':
                continue
            if not ready_snapshot(session, job.asset_id, job.version) or not (RENDER_DIR / job.key / 'map.pmtiles').is_file():
                continue
            with (RENDER_DIR / job.key / 'map.pmtiles').open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != job.sha256:
                    job.error = '显示归档校验失败，保留原文件'
                    job.status, job.stage = 'failed', '显示归档校验失败，使用视野显示'
                    session.commit()
                    continue
            # Canonical export and the worker never read the upload file. The
            # same deletion lock protects original downloads and reconciliation.
            parts = local_parts(version.entry_url)
            if not parts or parts[0] != asset.id:
                continue
            source = (FILES_DIR / parts[0] / parts[1]).resolve()
            if not source.is_relative_to((FILES_DIR / asset.id).resolve()):
                raise ValueError('原文件清理路径越界')
            staged = STORAGE_DIR / 'expired-sources' / job.key
            staged.parent.mkdir(parents=True, exist_ok=True)
            if source.is_file():
                source.rename(staged)
            try:
                for related in session.scalars(select(RenderJob).where(RenderJob.asset_id == job.asset_id,
                    RenderJob.version == job.version)):
                    related.source_state = 'expired'
                asset.byte_size = sum(p.stat().st_size for p in (FILES_DIR / asset.id).rglob('*') if p.is_file())
                asset.file_count = sum(1 for p in (FILES_DIR / asset.id).rglob('*') if p.is_file())
                session.commit()
            except Exception:
                session.rollback()
                if staged.exists():
                    staged.rename(source)
                raise
            staged.unlink(missing_ok=True)
        # Finish a crash after committing expired state but before unlinking.
        for job in session.scalars(select(RenderJob).where(RenderJob.source_state == 'expired')):
            (STORAGE_DIR / 'expired-sources' / job.key).unlink(missing_ok=True)


def recover_retention():
    """Recover a rename interrupted before its database commit, before scanning."""
    from app.services.assets import _deletion_lock, local_parts, lock_catalog
    from app.database import FILES_DIR
    with _deletion_lock, SessionLocal() as session:
        lock_catalog(session)
        for previous in RENDER_DIR.glob('*.previous'):
            key = previous.name.removesuffix('.previous')
            if len(key) != 64 or any(char not in '0123456789abcdef' for char in key):
                continue
            target = RENDER_DIR / key
            job = session.get(RenderJob, key)
            matches = False
            if job and target.is_dir() and (target / 'map.pmtiles').is_file():
                with (target / 'map.pmtiles').open('rb') as stream:
                    matches = hashlib.file_digest(stream, 'sha256').hexdigest() == job.sha256
            if matches or not job or not session.get(Asset, job.asset_id):
                shutil.rmtree(previous)
            else:
                if target.exists():
                    shutil.rmtree(target)
                previous.rename(target)
        for job in session.scalars(select(RenderJob)):
            staged = STORAGE_DIR / 'expired-sources' / job.key
            if not staged.exists():
                continue
            if job.source_state == 'expired':
                staged.unlink()
                continue
            version = session.get(AssetVersion, (job.asset_id, job.version))
            parts = local_parts(version.entry_url) if version else None
            if parts and parts[0] == job.asset_id:
                target = (FILES_DIR / parts[0] / parts[1]).resolve()
                if not target.is_relative_to((FILES_DIR / job.asset_id).resolve()):
                    raise ValueError('原文件恢复路径越界')
                if not target.exists():
                    staged.rename(target)


class RenderQueue:
    def __init__(self):
        self._guard, self._stop = Lock(), Event()
        self._users, self._thread = 0, None

    def acquire(self):
        with self._guard:
            self._users += 1
            if self._users == 1:
                self._stop.clear()
                self._thread = Thread(target=self._loop, name='city-render-queue', daemon=True)
                self._thread.start()

    def release(self):
        with self._guard:
            self._users -= 1
            if not self._users:
                self._stop.set()
                self._thread.join(timeout=35)

    def _loop(self):
        next_scan, next_expiry = datetime.min, datetime.min
        while not self._stop.is_set():
            self._active_key = None
            try:
                clock = now()
                if clock >= next_expiry:
                    expire_sources(clock)
                    next_expiry = next_source_check(clock)
                config = configuration()
                if config['url'] and config['token']:
                    if clock >= next_scan:
                        with SessionLocal() as session:
                            scan(session)
                        next_scan = clock + timedelta(seconds=15)
                    self.tick()
            except HTTPError as error:
                if error.code in (400, 401, 403, 404, 409, 410, 422):
                    with SessionLocal() as session:
                        job = session.get(RenderJob, self._active_key) if self._active_key else None
                        if job and job.status in ('running', 'queued'):
                            if error.code == 404 and job.attempts == 0:
                                job.remote_id, job.status, job.attempts = None, 'queued', 1
                            else:
                                job.status = 'failed'
                            job.error = f'切片服务请求失败（HTTP {error.code}），可重试'
                            session.commit()
                logger.exception('切片服务请求失败')
            except (ValueError, KeyError, TypeError) as error:
                with SessionLocal() as session:
                    job = session.get(RenderJob, self._active_key) if self._active_key else None
                    if job and job.status in ('running', 'queued'):
                        job.status, job.error, job.stage = 'failed', str(error)[:2000], '处理失败，使用视野显示'
                        session.commit()
                logger.exception('显示切片数据校验失败')
            except Exception:
                logger.exception('显示切片后台处理失败')
            self._stop.wait(3)

    def tick(self):
        from app.services.assets import lock_catalog
        from app.services.geojson_snapshot import ensure_snapshot
        self.cleanup_remote()
        with SessionLocal() as session:
            lock_catalog(session)
            displayed = exists(select(Layer.id).where(Layer.asset_id == RenderJob.asset_id,
                Layer.asset_version == RenderJob.version, Layer.map_attached.is_(True)))
            job = session.scalar(select(RenderJob).where(RenderJob.recipe == RECIPE,
                                 RenderJob.status.in_(('running', 'queued')))
                                 .order_by((RenderJob.status == 'running').desc(), displayed.desc(), RenderJob.created_at, RenderJob.key).limit(1))
            if not job:
                session.rollback()
                return
            self._active_key = job.key
            asset = session.get(Asset, job.asset_id)
            if not eligible(session, asset, job.version):
                job.status, job.stage = 'cancelled', '来源版本已不可用'
                session.commit()
                return
            key, remote_id = job.key, job.remote_id
            if not remote_id:
                if not ensure_snapshot(session, job.asset_id, job.version):
                    raise ValueError('完整数据快照不可用')
                session.commit()
                config = configuration()
                payload = {'key': key, 'asset_id': job.asset_id, 'version': job.version, 'profile': job.profile,
                    'recipe': RECIPE, 'retry': job.attempts > 0, 'source_mode': 'push',
                    'source_url': f"{config['backend'].rstrip('/')}/internal/render-source/{job.asset_id}/{job.version}"}
                with remote('POST', '/internal/jobs', payload) as response:
                    state = json.load(response)
                session.refresh(job)
                if job.status == 'cancelled':
                    job.remote_id = state['id']
                    session.commit()
                    return
                job.remote_id, job.status = state['id'], 'running'
                session.commit()
                remote_id = state['id']
            else:
                session.commit()
            with remote('GET', f'/internal/jobs/{remote_id}') as response:
                state = json.load(response)
            if state.get('needs_source'):
                state = push_source(remote_id, job.asset_id, job.version)
            session.refresh(job)
            if job.status == 'cancelled':
                return
            job.stage, job.error, job.updated_at = state.get('stage') or '', state.get('error') or '', now()
            if state['status'] in ('failed', 'cancelled'):
                job.status = state['status']
            session.commit()
        if state['status'] == 'succeeded':
            temporary = STORAGE_DIR / 'tmp'
            temporary.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='render-', dir=temporary) as folder:
                bundle = Path(folder) / 'artifact.zip'
                with remote('GET', f'/internal/jobs/{remote_id}/artifact') as response, bundle.open('wb') as output:
                    while chunk := response.read(1024**2):
                        if self._stop.is_set():
                            return
                        output.write(chunk)
                with bundle.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if state.get('artifact_sha256') and digest != state['artifact_sha256']:
                    raise ValueError('传输后的切片产物摘要不一致')
                try:
                    publish(key, bundle)
                except (ValueError, KeyError, TypeError) as error:
                    with SessionLocal() as failed_session:
                        failed = failed_session.get(RenderJob, key)
                        if failed and failed.status != 'cancelled':
                            failed.status, failed.error = 'failed', str(error)[:2000]
                            failed.stage = '产物校验失败，使用视野显示'
                            failed_session.commit()
                    return
            with remote('DELETE', f'/internal/jobs/{remote_id}/artifact'):
                pass
            with SessionLocal() as session:
                finished = session.get(RenderJob, key)
                if finished:
                    finished.remote_id = None
                    session.commit()
        self.cleanup_remote()

    def cleanup_remote(self):
        with SessionLocal() as session:
            for job in session.scalars(select(RenderJob).where(RenderJob.status.in_(('cancelled', 'succeeded', 'failed')))):
                if job.remote_id:
                    try:
                        if job.status != 'succeeded':
                            with remote('POST', f'/internal/jobs/{job.remote_id}/cancel'):
                                pass
                        with remote('DELETE', f'/internal/jobs/{job.remote_id}/artifact'):
                            pass
                    except HTTPError as error:
                        if error.code != 404:
                            raise
                    job.remote_id = None
                if not session.get(Asset, job.asset_id):
                    session.delete(job)
            session.commit()


render_queue = RenderQueue()

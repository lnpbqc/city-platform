"""Public derivative status and token-protected worker source streams."""
from typing import Annotated
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .assets import lock_catalog
from .database import get_session
from .errors import ApiProblem
from .models import Asset, AssetVersion
from .render_models import RenderJob
from .rendering import RECIPE, RENDER_DIR, configuration, describe, enqueue

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def check_token(authorization):
    token = configuration()['token']
    if not token or not secrets.compare_digest(authorization or '', 'Bearer ' + token):
        raise HTTPException(401, '内部服务凭据无效')


def require_snapshot(session, asset_id, version):
    from .geojson_snapshot import ready_snapshot
    asset = session.get(Asset, asset_id)
    if not asset or asset.status != 'active' or not session.get(AssetVersion, (asset_id, version)):
        raise ApiProblem(404, 'ASSET_VERSION_NOT_FOUND', '资产版本不可用')
    if not ready_snapshot(session, asset_id, version):
        raise ApiProblem(409, 'SNAPSHOT_UNAVAILABLE', '完整数据快照尚未就绪')


@router.get('/internal/render-source/{asset_id}/{version}')
def worker_source(asset_id: str, version: str, session: SessionDep,
                  authorization: Annotated[str | None, Header()] = None):
    check_token(authorization)
    require_snapshot(session, asset_id, version)
    from .geojson_snapshot import iter_export
    from .geojson_snapshot import ready_snapshot
    snapshot = ready_snapshot(session, asset_id, version)
    return StreamingResponse(iter_export(asset_id, version, identified=True), media_type='application/geo+json',
        headers={'X-Snapshot-Sha256': snapshot.sha256, 'X-Feature-Count': str(snapshot.feature_count)})


@router.get('/api/assets/{asset_id}/versions/{version}/geojson')
def export_geojson(asset_id: str, version: str, session: SessionDep):
    require_snapshot(session, asset_id, version)
    from .geojson_snapshot import iter_export
    return StreamingResponse(iter_export(asset_id, version), media_type='application/geo+json',
        headers={'Content-Disposition': 'attachment; filename="data.geojson"'})


@router.get('/api/assets/{asset_id}/versions/{version}/render')
def render_status(asset_id: str, version: str, session: SessionDep, category: str | None = None):
    if not session.get(AssetVersion, (asset_id, version)):
        raise ApiProblem(404, 'ASSET_VERSION_NOT_FOUND', '资产版本不存在')
    return describe(session, asset_id, version, category)


@router.post('/api/assets/{asset_id}/versions/{version}/render/retry')
def retry_render(asset_id: str, version: str, session: SessionDep, category: str = ''):
    lock_catalog(session)
    job = enqueue(session, asset_id, version, category)
    if not job:
        raise ApiProblem(409, 'RENDER_NOT_APPLICABLE', '该版本不参与普通地图切片')
    if job.status in ('failed', 'cancelled'):
        job.status, job.remote_id, job.error, job.stage = 'queued', None, '', '等待重新切片'
        job.attempts += 1
    session.commit()
    return describe(session, asset_id, version, category)


@router.post('/api/assets/{asset_id}/versions/{version}/render/cancel')
def cancel_render(asset_id: str, version: str, session: SessionDep):
    lock_catalog(session)
    for job in session.scalars(select(RenderJob).where(RenderJob.asset_id == asset_id,
        RenderJob.version == version, RenderJob.status.in_(('running', 'queued')))):
        job.status, job.stage = 'cancelled', '已取消切片，使用视野显示'
    session.commit()
    return describe(session, asset_id, version)


@router.get('/api/render-files/{key}/map.pmtiles')
def archive(key: str, request: Request, session: SessionDep):
    job = session.get(RenderJob, key)
    if not job or job.status != 'succeeded' or job.recipe != RECIPE:
        raise ApiProblem(404, 'RENDER_NOT_FOUND', '显示归档未就绪')
    asset = session.get(Asset, job.asset_id)
    target = RENDER_DIR / job.key / 'map.pmtiles'
    if not asset or asset.status != 'active' or not target.is_file():
        raise ApiProblem(404, 'RENDER_NOT_FOUND', '显示归档不可用')
    etag = f'"{job.sha256}"'
    matches = [part.strip().removeprefix('W/') for part in request.headers.get('if-none-match', '').split(',')]
    if etag in matches or '*' in matches:
        return Response(status_code=304, headers={'ETag': etag, 'Cache-Control': 'public, max-age=31536000, immutable'})
    return FileResponse(target, media_type='application/vnd.pmtiles',
        headers={'ETag': etag, 'Cache-Control': 'public, max-age=31536000, immutable'})

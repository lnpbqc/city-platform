from typing import Annotated
import secrets

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.routers.dependencies import SessionDep
from app.services import render_assets
from app.services.rendering import configuration

router = APIRouter()


def check_token(authorization):
    token = configuration()['token']
    if not token or not secrets.compare_digest(authorization or '', 'Bearer ' + token):
        raise HTTPException(401, '内部服务凭据无效')


@router.get('/internal/render-source/{asset_id}/{version}')
def worker_source(asset_id: str, version: str, session: SessionDep,
                  authorization: Annotated[str | None, Header()] = None):
    check_token(authorization)
    snapshot = render_assets.require_snapshot(session, asset_id, version)
    from app.services.geojson_snapshot import iter_export
    return StreamingResponse(iter_export(asset_id, version, identified=True), media_type='application/geo+json',
        headers={'X-Snapshot-Sha256': snapshot.sha256, 'X-Feature-Count': str(snapshot.feature_count)})


@router.get('/api/assets/{asset_id}/versions/{version}/geojson')
def export_geojson(asset_id: str, version: str, session: SessionDep):
    render_assets.require_snapshot(session, asset_id, version)
    from app.services.geojson_snapshot import iter_export
    return StreamingResponse(iter_export(asset_id, version), media_type='application/geo+json',
        headers={'Content-Disposition': 'attachment; filename="data.geojson"'})


@router.get('/api/assets/{asset_id}/versions/{version}/render')
def render_status(asset_id: str, version: str, session: SessionDep, category: str | None = None):
    return render_assets.render_status(asset_id, version, session, category)


@router.post('/api/assets/{asset_id}/versions/{version}/render/retry')
def retry_render(asset_id: str, version: str, session: SessionDep, category: str = ''):
    return render_assets.retry_render(asset_id, version, session, category)


@router.post('/api/assets/{asset_id}/versions/{version}/render/cancel')
def cancel_render(asset_id: str, version: str, session: SessionDep):
    return render_assets.cancel_render(asset_id, version, session)


@router.get('/api/render-files/{key}/map.pmtiles')
def archive(key: str, request: Request, session: SessionDep):
    target, sha256 = render_assets.archive_file(session, key)
    etag = f'"{sha256}"'
    matches = [part.strip().removeprefix('W/') for part in request.headers.get('if-none-match', '').split(',')]
    if etag in matches or '*' in matches:
        return Response(status_code=304, headers={'ETag': etag, 'Cache-Control': 'public, max-age=31536000, immutable'})
    return FileResponse(target, media_type='application/vnd.pmtiles',
        headers={'ETag': etag, 'Cache-Control': 'public, max-age=31536000, immutable'})

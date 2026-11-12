from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.assets import lock_catalog
from app.errors import ApiProblem
from app.models import Asset, AssetVersion
from app.models.render import RenderJob
from app.services.rendering import RECIPE, RENDER_DIR, describe, enqueue


def require_snapshot(session: Session, asset_id: str, version: str):
    from app.services.geojson_snapshot import ready_snapshot
    asset = session.get(Asset, asset_id)
    if not asset or asset.status != 'active' or not session.get(AssetVersion, (asset_id, version)):
        raise ApiProblem(404, 'ASSET_VERSION_NOT_FOUND', '资产版本不可用')
    snapshot = ready_snapshot(session, asset_id, version)
    if not snapshot:
        raise ApiProblem(409, 'SNAPSHOT_UNAVAILABLE', '完整数据快照尚未就绪')
    return snapshot


def render_status(asset_id: str, version: str, session: Session, category: str | None):
    if not session.get(AssetVersion, (asset_id, version)):
        raise ApiProblem(404, 'ASSET_VERSION_NOT_FOUND', '资产版本不存在')
    return describe(session, asset_id, version, category)


def retry_render(asset_id: str, version: str, session: Session, category: str):
    lock_catalog(session)
    job = enqueue(session, asset_id, version, category)
    if not job:
        raise ApiProblem(409, 'RENDER_NOT_APPLICABLE', '该版本不参与普通地图切片')
    if job.status in ('failed', 'cancelled'):
        job.status, job.remote_id, job.error, job.stage = 'queued', None, '', '等待重新切片'
        job.attempts += 1
    session.commit()
    return describe(session, asset_id, version, category)


def cancel_render(asset_id: str, version: str, session: Session):
    lock_catalog(session)
    for job in session.scalars(select(RenderJob).where(RenderJob.asset_id == asset_id,
        RenderJob.version == version, RenderJob.status.in_(('running', 'queued')))):
        job.status, job.stage = 'cancelled', '已取消切片，使用视野显示'
    session.commit()
    return describe(session, asset_id, version)


def archive_file(session: Session, key: str):
    job = session.get(RenderJob, key)
    if not job or job.status != 'succeeded' or job.recipe != RECIPE:
        raise ApiProblem(404, 'RENDER_NOT_FOUND', '显示归档未就绪')
    asset = session.get(Asset, job.asset_id)
    target = RENDER_DIR / job.key / 'map.pmtiles'
    if not asset or asset.status != 'active' or not target.is_file():
        raise ApiProblem(404, 'RENDER_NOT_FOUND', '显示归档不可用')
    return target, job.sha256

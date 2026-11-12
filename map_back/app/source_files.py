"""Snapshot raw GeoJSON reads before releasing the cross-process catalog lock."""
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .assets import local_parts, prepare_download
from .database import SessionLocal
from .models import Asset
from .uploads import cleanup


class SourceFiles(StaticFiles):
    async def get_response(self, path, scope):
        parts = path.replace('\\', '/').split('/')
        identity = None
        if len(parts) >= 2:
            with SessionLocal() as session:
                asset = session.get(Asset, parts[0])
                if asset and asset.status == 'active' and asset.type == 'geojson' and asset.source_kind == 'upload':
                    entry = local_parts(asset.entry_url)
                    if entry and entry[1] == '/'.join(parts[1:]):
                        identity = asset.id
        if identity:
            def snapshot():
                with SessionLocal() as session:
                    return prepare_download(session, identity)
            target, filename, media_type, temporary = await run_in_threadpool(snapshot)
            return FileResponse(target, media_type=media_type,
                                background=BackgroundTask(cleanup, temporary))
        return await super().get_response(path, scope)

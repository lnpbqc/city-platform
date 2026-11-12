"""Snapshot raw GeoJSON reads before releasing the cross-process catalog lock."""
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.database import SessionLocal
from app.services.assets import prepare_download, published_geojson_identity
from app.services.uploads import cleanup


class SourceFiles(StaticFiles):
    async def get_response(self, path, scope):
        parts = path.replace('\\', '/').split('/')
        identity = None
        if len(parts) >= 2:
            with SessionLocal() as session:
                identity = published_geojson_identity(session, parts[0], '/'.join(parts[1:]))
        if identity:
            def snapshot():
                with SessionLocal() as session:
                    return prepare_download(session, identity)
            target, _, media_type, temporary = await run_in_threadpool(snapshot)
            return FileResponse(target, media_type=media_type,
                                background=BackgroundTask(cleanup, temporary))
        return await super().get_response(path, scope)

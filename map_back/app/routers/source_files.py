"""Serve current local source files, with snapshot reads for mutable content."""
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from app.database import FILES_DIR, SessionLocal
from app.models import Asset
from app.services.assets import can_calibrate, directory, lock_catalog, prepare_download, published_geojson_identity, version_file
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
        if len(parts) >= 2 and parts[-1].lower().endswith(".json"):
            def manifest():
                with SessionLocal() as session:
                    lock_catalog(session)
                    asset = session.get(Asset, parts[0])
                    if can_calibrate(asset):
                        try:
                            root = directory(FILES_DIR, parts[0])
                            return Response(version_file(root, '/'.join(parts[1:])).read_bytes(),
                                            media_type="application/json", headers={"Cache-Control": "no-store"})
                        except (OSError, ValueError):
                            return Response(status_code=404, headers={"Cache-Control": "no-store"})
                    return None
            response = await run_in_threadpool(manifest)
            if response is not None:
                return response
        return await super().get_response(path, scope)

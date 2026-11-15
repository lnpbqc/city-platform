import shutil
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from app.services.assets import delete_asset, prepare_download
from app.errors import ApiProblem
from app.schemas.assets import AssetDetail, ReconcileOutput
from app.routers.dependencies import SessionDep
from app.services import asset_maintenance
from app.services.tiles_download import download_version, stream_zip

router = APIRouter()


@router.post("/api/assets/reconcile", response_model=ReconcileOutput)
def reconcile_assets(session: SessionDep):
    return asset_maintenance.reconcile_assets(session)


@router.get("/api/assets/{asset_id}", response_model=AssetDetail)
def get_asset(asset_id: str, session: SessionDep):
    return asset_maintenance.get_asset(asset_id, session)


@router.delete("/api/assets/{asset_id}", status_code=204)
def remove_asset(asset_id: str, session: SessionDep):
    delete_asset(session, asset_id)


@router.get("/api/assets/{asset_id}/download")
def download_asset(asset_id: str, session: SessionDep):
    target, filename, media_type, temporary = prepare_download(session, asset_id)
    return FileResponse(target, filename=filename, media_type=media_type,
                        background=BackgroundTask(shutil.rmtree, temporary))


@router.get("/api/assets/{asset_id}/versions/{version}/download")
def download_asset_version(asset_id: str, version: str, session: SessionDep, revision: int | None = None):
    return _tiles_zip(session, asset_id, version, revision)


def _tiles_zip(session: SessionDep, asset_id: str, version: str | None = None, revision: int | None = None):
    root, files, headers = download_version(session, asset_id, version, revision=revision)

    def download():
        try:
            yield from stream_zip(root, files)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    return StreamingResponse(download(), media_type="application/zip", headers=headers,
                             background=BackgroundTask(shutil.rmtree, root, ignore_errors=True))


@router.head("/api/assets/{asset_id}/versions/{version}/download", include_in_schema=False)
def check_download_version(asset_id: str, version: str, session: SessionDep, revision: int | None = None):
    try:
        _, _, headers = download_version(session, asset_id, version, revision=revision, snapshot=False)
    except ApiProblem as error:
        # HEAD has no response body; keep the actionable message available to the download control.
        error.headers = {**(error.headers or {}), "X-Download-Error": quote(error.message, safe="")}
        raise
    return Response(media_type="application/zip", headers=headers)

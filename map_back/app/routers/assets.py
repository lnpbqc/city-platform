import shutil

from fastapi import APIRouter
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.services.assets import delete_asset, prepare_download
from app.schemas.assets import AssetDetail, ReconcileOutput
from app.routers.dependencies import SessionDep
from app.services import asset_maintenance

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

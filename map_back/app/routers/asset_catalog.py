from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.schemas.assets import AssetRegisterInput, AssetVersionOutput, TilesCalibrationInput
from app.routers.dependencies import SessionDep
from app.services import asset_catalog
from app.services.tiles_calibration import get_calibrated_file, publish_calibration

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.post("/register", response_model=AssetVersionOutput, status_code=201)
def register_asset(body: AssetRegisterInput, session: SessionDep):
    return asset_catalog.register_asset(body, session)


@router.get("/{asset_id}/versions", response_model=list[AssetVersionOutput])
def list_versions(asset_id: str, session: SessionDep):
    return asset_catalog.list_versions(asset_id, session)


@router.post("/{asset_id}/versions/calibrate", response_model=AssetVersionOutput, status_code=201)
def calibrate(asset_id: str, body: TilesCalibrationInput, session: SessionDep):
    return publish_calibration(session, asset_id, body)


@router.get("/{asset_id}/versions/{version}", response_model=AssetVersionOutput)
def get_version(asset_id: str, version: str, session: SessionDep):
    return asset_catalog.get_version(asset_id, version, session)


@router.get("/{asset_id}/versions/{version}/tiles/{path:path}")
@router.head("/{asset_id}/versions/{version}/tiles/{path:path}", include_in_schema=False)
def get_tiles_version_file(asset_id: str, version: str, path: str, session: SessionDep):
    source = get_calibrated_file(session, asset_id, version, path)
    return FileResponse(source, headers={"Cache-Control": "no-store"} if source.suffix.lower() == ".json" else None)

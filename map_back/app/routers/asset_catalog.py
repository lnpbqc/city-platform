from fastapi import APIRouter

from app.schemas.assets import AssetRegisterInput, AssetVersionOutput
from app.routers.dependencies import SessionDep
from app.services import asset_catalog

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.post("/register", response_model=AssetVersionOutput, status_code=201)
def register_asset(body: AssetRegisterInput, session: SessionDep):
    return asset_catalog.register_asset(body, session)


@router.get("/{asset_id}/versions", response_model=list[AssetVersionOutput])
def list_versions(asset_id: str, session: SessionDep):
    return asset_catalog.list_versions(asset_id, session)


@router.get("/{asset_id}/versions/{version}", response_model=AssetVersionOutput)
def get_version(asset_id: str, version: str, session: SessionDep):
    return asset_catalog.get_version(asset_id, version, session)

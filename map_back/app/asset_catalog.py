"""External asset registration and immutable version lookup."""
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .assets import ensure_initial_version, external_registration_key, local_parts, lock_catalog, version_record
from .contracts import AssetRegisterInput, AssetVersionOutput
from .database import get_session
from .errors import ApiProblem
from .models import Asset, AssetVersion
from .builtin_assets import builtin_asset_for_url
from .object_index import index_asset

router = APIRouter(prefix="/api/assets", tags=["assets"])
SessionDep = Annotated[Session, Depends(get_session)]


def registered_asset(session: Session, identity: str):
    asset = session.get(Asset, identity)
    if asset is None:
        raise ApiProblem(404, "ASSET_NOT_FOUND", "文件资产不存在")
    return asset


@router.post("/register", response_model=AssetVersionOutput, status_code=201)
def register_asset(body: AssetRegisterInput, session: SessionDep):
    lock_catalog(session)
    parts = local_parts(body.location)
    builtin_id = builtin_asset_for_url(body.location)
    if parts or builtin_id:
        asset = session.get(Asset, builtin_id or parts[0])
        if asset is None:
            raise ApiProblem(422, "CONTENT_INVALID", "请先扫描已有本地文件，再登记图层")
        raise ApiProblem(409, "ASSET_ALREADY_REGISTERED", "该受管资产已登记，可直接创建图层引用", {"asset_id": asset.id})
    key = external_registration_key(body.location)
    existing = session.scalar(select(Asset).where(Asset.registration_key == key))
    if existing:
        raise ApiProblem(409, "ASSET_ALREADY_REGISTERED", "该外部地址已登记", {"asset_id": existing.id})
    asset = Asset(id=str(uuid4()), original_name=None, name=body.name, type=body.type,
                  entry_url=key, registration_key=key, source_kind="external", protected=False,
                  source=body.source, coordinate_description=body.coordinate_description,
                  byte_size=0, file_count=0, status="active", error="")
    session.add(asset)
    try:
        session.flush()
        version = ensure_initial_version(session, asset)
        index_asset(session, asset, version)
        session.commit()
    except IntegrityError:
        session.rollback()
        duplicate = session.scalar(select(Asset).where(Asset.registration_key == key))
        if duplicate:
            raise ApiProblem(409, "ASSET_ALREADY_REGISTERED", "该外部地址已登记", {"asset_id": duplicate.id})
        raise
    return version_record(asset, version)


@router.get("/{asset_id}/versions", response_model=list[AssetVersionOutput])
def list_versions(asset_id: str, session: SessionDep):
    asset = registered_asset(session, asset_id)
    versions = session.scalars(select(AssetVersion).where(AssetVersion.asset_id == asset_id)
                               .order_by(AssetVersion.created_at.desc(), AssetVersion.version))
    return [version_record(asset, version) for version in versions]


@router.get("/{asset_id}/versions/{version}", response_model=AssetVersionOutput)
def get_version(asset_id: str, version: str, session: SessionDep):
    asset = registered_asset(session, asset_id)
    record = session.get(AssetVersion, (asset_id, version))
    if record is None:
        raise ApiProblem(404, "ASSET_VERSION_NOT_FOUND", "资产版本不存在")
    return version_record(asset, record)

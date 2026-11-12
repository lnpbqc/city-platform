from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.cruds import assets as asset_records
from app.routers.dependencies import SessionDep
from app.schemas.assets import AssetOutput, StatsOverview
from app.schemas.common import Page
from app.services import asset_queries
from app.services.builtin_assets import RETIRED_ASSET_IDS
from app.services.rendering import storage_usage

router = APIRouter(prefix="/api")


@router.get("/assets", response_model=list[AssetOutput] | Page[AssetOutput])
def list_assets(
    session: SessionDep,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=100)] = None,
    type: Literal["geojson", "3dtiles", "network", "unknown"] | None = None,
    status: Literal["active", "ready", "deleting", "delete_error", "missing", "unsafe"] | None = None,
    q: Annotated[str | None, Query(max_length=500)] = None,
    from_time: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_time: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    sort: Literal["byte_size", "-byte_size"] | None = None,
):
    return asset_queries.list_assets(session, page, page_size, type, status, q, from_time, to_time, sort)


@router.get("/stats/overview", response_model=StatsOverview)
def stats_overview(session: SessionDep):
    return asset_records.stats_overview(session, RETIRED_ASSET_IDS)


@router.get('/stats/storage')
def stats_storage():
    return storage_usage()

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session

from .assets import asset_record
from .contracts import Page, StatsOverview
from .database import get_session
from .errors import ApiProblem
from .models import Asset, Run, SpatialObject
from .schemas import AssetOutput

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]
created_at = func.coalesce(Asset.uploaded_at, Asset.discovered_at)


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
    start = from_time.astimezone(timezone.utc).replace(tzinfo=None) if from_time else None
    end = to_time.astimezone(timezone.utc).replace(tzinfo=None) if to_time else None
    if start and end and start > end:
        raise ApiProblem(422, "VALIDATION_ERROR", "from 不能晚于 to")
    filters = []
    if type:
        filters.append(Asset.type == type)
    if status:
        filters.append(Asset.status == ("active" if status == "ready" else status))
    if q and q.strip():
        filters.append(or_(*(column.icontains(q.strip(), autoescape=True)
                            for column in (Asset.id, Asset.name, Asset.original_name, Asset.source))))
    if start:
        filters.append(created_at >= start)
    if end:
        filters.append(created_at <= end)
    ordering = [created_at.desc(), Asset.id.asc()]
    if sort:
        known_size = case((Asset.source_kind == "external", None), else_=Asset.byte_size)
        ordering = [known_size.is_(None), known_size.desc() if sort.startswith("-") else known_size.asc(), Asset.id.asc()]
    statement = select(Asset).where(*filters).order_by(*ordering)
    if page is None and page_size is None:
        return [asset_record(session, asset, inspect_files=not filters and sort is None)
                for asset in session.scalars(statement)]
    page, page_size = page or 1, page_size or 20
    total = session.scalar(select(func.count()).select_from(Asset).where(*filters))
    offset = (page - 1) * page_size
    if offset >= total:
        return {"items": [], "total": total, "page": page, "page_size": page_size}
    items = [asset_record(session, asset, inspect_files=False)
             for asset in session.scalars(statement.offset(offset).limit(page_size))]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/stats/overview", response_model=StatsOverview)
def stats_overview(session: SessionDep):
    if session.bind.dialect.name == "sqlite" and not session.in_transaction():
        session.execute(text("BEGIN"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    counts = dict(session.execute(select(Asset.type, func.count()).group_by(Asset.type)).all())
    capacity = session.scalar(select(func.coalesce(func.sum(Asset.byte_size), 0)).where(Asset.source_kind != "external"))
    recent = session.scalar(select(func.count()).select_from(Asset).where(created_at >= now - timedelta(days=7), created_at <= now))
    objects = session.scalar(select(func.count()).select_from(SpatialObject).join(Asset, Asset.id == SpatialObject.asset_id)
                             .where(Asset.status == "active", Asset.current_version == SpatialObject.asset_version))
    return {"asset_count": sum(counts.values()), "object_count": objects, "run_count": session.scalar(select(func.count()).select_from(Run)), "total_byte_size": capacity,
            "assets_by_type": counts, "assets_added_last_7_days": recent}

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.orm import Session

from app.models import Asset, Run, SpatialObject

created_at = func.coalesce(Asset.uploaded_at, Asset.discovered_at)


def query_assets(session: Session, excluded, *, kind, status, q, start, end, sort, page, page_size):
    in_catalog = Asset.id.not_in(excluded)
    filters = []
    if kind:
        filters.append(Asset.type == kind)
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
    statement = select(Asset).where(in_catalog, *filters).order_by(*ordering)
    if page is None:
        return session.scalars(statement), None
    total = session.scalar(select(func.count()).select_from(Asset).where(in_catalog, *filters))
    offset = (page - 1) * page_size
    return ([] if offset >= total else session.scalars(statement.offset(offset).limit(page_size))), total


def stats_overview(session: Session, excluded):
    in_catalog = Asset.id.not_in(excluded)
    if session.bind.dialect.name == "sqlite" and not session.in_transaction():
        session.execute(text("BEGIN"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    counts = dict(session.execute(select(Asset.type, func.count()).where(in_catalog).group_by(Asset.type)).all())
    capacity = session.scalar(select(func.coalesce(func.sum(Asset.byte_size), 0)).where(in_catalog, Asset.source_kind != "external"))
    recent = session.scalar(select(func.count()).select_from(Asset).where(in_catalog, created_at >= now - timedelta(days=7), created_at <= now))
    objects = session.scalar(select(func.count()).select_from(SpatialObject).join(Asset, Asset.id == SpatialObject.asset_id)
                             .where(in_catalog, Asset.status == "active", Asset.current_version == SpatialObject.asset_version))
    return {"asset_count": sum(counts.values()), "object_count": objects, "run_count": session.scalar(select(func.count()).select_from(Run)), "total_byte_size": capacity,
            "assets_by_type": counts, "assets_added_last_7_days": recent}

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Run, RunAssetReference


def run_by_key(session: Session, key: str):
    return session.scalar(select(Run).where(Run.idempotency_key == key))


def run_references(session: Session, identity: str):
    return set(session.execute(select(RunAssetReference.asset_id, RunAssetReference.asset_version)
                               .where(RunAssetReference.run_id == identity)).all())


def run_page(session: Session, page: int, page_size: int, scene_id, status, start, end):
    if session.bind.dialect.name == "sqlite" and not session.in_transaction():
        session.execute(text("BEGIN"))
    filters = []
    if scene_id is not None:
        filters.append(Run.scene_id == scene_id)
    if status:
        filters.append(Run.status == status)
    if start:
        filters.append(Run.submitted_at >= start)
    if end:
        filters.append(Run.submitted_at <= end)
    total = session.scalar(select(func.count()).select_from(Run).where(*filters))
    offset = (page - 1) * page_size
    rows = [] if offset >= total else session.scalars(select(Run).where(*filters)
        .order_by(Run.submitted_at.desc(), Run.id).offset(offset).limit(page_size))
    return rows, total

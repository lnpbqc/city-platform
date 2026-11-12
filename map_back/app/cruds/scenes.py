from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from app.models import Scene, SceneAssetReference


def scene_page(session: Session, page: int, page_size: int, q: str):
    if session.bind.dialect.name == "sqlite" and not session.in_transaction():
        session.execute(text("BEGIN"))
    scenes = select(Scene)
    search = q.strip()
    if search:
        scenes = scenes.where(or_(Scene.id == search, Scene.document["name"].as_string().icontains(search, autoescape=True)))
        scenes = scenes.order_by((Scene.id == search).desc())
    total = session.scalar(select(func.count()).select_from(scenes.order_by(None).subquery()))
    start = (page - 1) * page_size
    records = [] if start >= total else session.scalars(scenes.order_by(Scene.updated_at.desc(), Scene.id)
                                                       .offset(start).limit(page_size))
    return records, total


def replace_references(session: Session, identity: str, references: set[tuple[str, str]]):
    session.execute(delete(SceneAssetReference).where(SceneAssetReference.scene_id == identity))
    session.add_all(SceneAssetReference(scene_id=identity, asset_id=asset_id, asset_version=version)
                    for asset_id, version in sorted(references))


def update_version(session: Session, identity: str, expected: int, document: dict,
                   network_id: str | None, network_version: str | None):
    return session.execute(update(Scene).where(Scene.id == identity, Scene.version == expected)
        .values(version=expected + 1, document=document, updated_at=datetime.now(timezone.utc),
                network_id=network_id, network_version=network_version)).rowcount


def delete_version(session: Session, identity: str, expected: int):
    return session.execute(delete(Scene).where(Scene.id == identity, Scene.version == expected)).rowcount

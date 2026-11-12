from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Bookmark


def list_bookmarks(session: Session):
    return session.scalars(select(Bookmark).order_by(Bookmark.created_at.desc(), Bookmark.id.desc())).all()


def scene_is_bookmarked(session: Session, identity: str):
    return session.scalar(select(Bookmark.id).where(
        Bookmark.kind == "scene", Bookmark.state["scene_id"].as_string() == identity).limit(1)) is not None

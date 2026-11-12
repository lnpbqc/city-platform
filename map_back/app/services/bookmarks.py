from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Bookmark, Run
from app.schemas.bookmarks import BookmarkInput, BookmarkRename
from app.errors import ApiProblem
from app.cruds.transactions import reserve_writer
from app.services.scenes import check_version, scene_record

def create_bookmark(body: BookmarkInput, session: Session):
    if body.kind == "scene":
        reserve_writer(session)
        state = body.state
        scene = scene_record(session, state.scene_id)
        check_version(scene, state.scene_version)
        if state.run_id is not None and session.get(Run, state.run_id) is None:
            raise ApiProblem(422, "RUN_NOT_FOUND", "运行记录不存在")
        if scene.document.get("run_id") != state.run_id:
            raise ApiProblem(422, "SCENE_RUN_MISMATCH", "收藏运行与场景保存的运行不一致")
    bookmark = Bookmark(id=str(uuid4()), **body.model_dump(mode="json"))
    session.add(bookmark)
    session.commit()
    session.refresh(bookmark)
    return bookmark


def rename_bookmark(bookmark_id: str, body: BookmarkRename, session: Session):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None:
        raise HTTPException(404, "位置收藏不存在")
    bookmark.name = body.name
    session.commit()
    session.refresh(bookmark)
    return bookmark


def delete_bookmark(bookmark_id: str, session: Session):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None:
        raise HTTPException(404, "位置收藏不存在")
    session.delete(bookmark)
    session.commit()

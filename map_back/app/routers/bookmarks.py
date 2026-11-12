from fastapi import APIRouter

from app.cruds import bookmarks as bookmark_records
from app.schemas.bookmarks import BookmarkInput, BookmarkOutput, BookmarkRename
from app.routers.dependencies import SessionDep
from app.services import bookmarks

router = APIRouter()


@router.get("/api/bookmarks", response_model=list[BookmarkOutput])
def list_bookmarks(session: SessionDep):
    return bookmark_records.list_bookmarks(session)


@router.post("/api/bookmarks", response_model=BookmarkOutput, status_code=201)
def create_bookmark(body: BookmarkInput, session: SessionDep):
    return bookmarks.create_bookmark(body, session)


@router.patch("/api/bookmarks/{bookmark_id}", response_model=BookmarkOutput)
def rename_bookmark(bookmark_id: str, body: BookmarkRename, session: SessionDep):
    return bookmarks.rename_bookmark(bookmark_id, body, session)


@router.delete("/api/bookmarks/{bookmark_id}", status_code=204)
def delete_bookmark(bookmark_id: str, session: SessionDep):
    return bookmarks.delete_bookmark(bookmark_id, session)

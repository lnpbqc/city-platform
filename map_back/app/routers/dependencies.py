from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_session

SessionDep = Annotated[Session, Depends(get_session)]


def get_query_session(session: SessionDep):
    # sqlite3 legacy transactions do not start on SELECT; keep count/page/detail
    # in one read snapshot when another request deletes an unreferenced asset.
    if session.bind.dialect.name == "sqlite" and not session.in_transaction():
        session.execute(text("BEGIN"))
    return session


QuerySessionDep = Annotated[Session, Depends(get_query_session)]

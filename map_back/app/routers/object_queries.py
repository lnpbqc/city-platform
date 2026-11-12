from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.schemas.objects import ObjectOutput, ObjectSummary
from app.schemas.common import Page
from app.routers.dependencies import QuerySessionDep as SessionDep
from app.services import object_queries
from app.schemas.objects import ObjectFilters
from app.schemas.objects import ObjectSelectionInput

router = APIRouter(prefix="/api/objects", tags=["objects"])


@router.get("", response_model=Page[ObjectOutput])
def list_objects(query: Annotated[ObjectFilters, Query()], session: SessionDep):
    return object_queries.list_objects(query, session)


@router.post("/select", response_model=Page[ObjectOutput])
def select_polygon(body: ObjectSelectionInput, session: SessionDep):
    return object_queries.select_polygon(body, session)


@router.get("/summary", response_model=ObjectSummary)
def summarize_objects(query: Annotated[ObjectFilters, Query()], session: SessionDep):
    return object_queries.summarize_objects(query, session)


@router.get("/{identity}", response_model=ObjectOutput)
def get_object(identity: str, session: SessionDep, time: AwareDatetime | None = None,
               resolution: Literal["hour", "day"] = "hour"):
    return object_queries.get_object(identity, session, time, resolution)

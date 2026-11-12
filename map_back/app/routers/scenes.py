import re
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response

from app.errors import ApiProblem
from app.schemas.common import Page
from app.schemas.scenes import SceneInput, SceneOutput
from app.routers.dependencies import SessionDep
from app.services import scenes

router = APIRouter(prefix="/api/scenes", tags=["scenes"])


def expected_version(value: str | None):
    if value is None:
        raise ApiProblem(400, "IF_MATCH_REQUIRED", '需要If-Match版本，例如"1"')
    match = re.fullmatch(r'"([1-9][0-9]*)"', value.strip())
    if match is None or len(match[1]) > 19:
        raise ApiProblem(400, "INVALID_IF_MATCH", 'If-Match须为单个带双引号的正整数版本')
    return int(match[1])


@router.post("", response_model=SceneOutput, status_code=201)
def create_scene(body: SceneInput, response: Response, session: SessionDep):
    result = scenes.create_scene(body, session)
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.get("", response_model=Page[SceneOutput])
def list_scenes(session: SessionDep, page: Annotated[int, Query(ge=1)] = 1,
                page_size: Annotated[int, Query(ge=1, le=100)] = 20,
                q: Annotated[str, Query(max_length=120)] = ""):
    return scenes.list_scenes(session, page, page_size, q)


@router.get("/{identity}", response_model=SceneOutput)
def get_scene(identity: str, response: Response, session: SessionDep,
              version: Annotated[int | None, Query(ge=1)] = None):
    result = scenes.get_scene(identity, session, version)
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.put("/{identity}", response_model=SceneOutput)
def update_scene(identity: str, body: SceneInput, response: Response, session: SessionDep,
                  if_match: Annotated[str | None, Header()] = None):
    result = scenes.update_scene(identity, body, session, expected_version(if_match))
    response.headers["ETag"] = f'"{result.version}"'
    return result


@router.delete("/{identity}", status_code=204)
def delete_scene(identity: str, session: SessionDep, if_match: Annotated[str | None, Header()] = None):
    return scenes.delete_scene(identity, session, expected_version(if_match))

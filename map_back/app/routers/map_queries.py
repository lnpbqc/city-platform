from fastapi import APIRouter

from app.routers.dependencies import QuerySessionDep as SessionDep
from app.services import map_queries
from app.schemas.map_queries import NearbyInput
from app.schemas.map_queries import RoadGroupsInput
from app.schemas.map_queries import RoadPickInput
from app.schemas.map_queries import ViewportInput

router = APIRouter(prefix='/api/map', tags=['map'])


@router.post('/road-groups')
def selected_road_groups(body: RoadGroupsInput, session: SessionDep):
    return map_queries.selected_road_groups(body, session)


@router.post('/viewport')
def viewport(body: ViewportInput, session: SessionDep):
    return map_queries.viewport(body, session)


@router.post('/road-pick')
def road_pick(body: RoadPickInput, session: SessionDep):
    return map_queries.road_pick(body, session)


@router.post('/nearby')
def nearby(body: NearbyInput, session: SessionDep):
    return map_queries.nearby(body, session)


@router.get('/objects/{identity}')
def detail(identity: str, session: SessionDep):
    return map_queries.detail(identity, session)

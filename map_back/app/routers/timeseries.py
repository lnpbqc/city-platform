from typing import Annotated

from fastapi import APIRouter, Query

from app.schemas.timeseries import LayerTimesOutput, TimeSeriesOutput
from app.routers.dependencies import QuerySessionDep as SessionDep
from app.services import timeseries
from app.schemas.timeseries import LayerTimeQuery
from app.schemas.timeseries import TimeSeriesQuery

router = APIRouter(tags=["timeseries"])


@router.get("/api/layers/{layer_id}/times", response_model=LayerTimesOutput)
def layer_times(layer_id: str, query: Annotated[LayerTimeQuery, Query()], session: SessionDep):
    return timeseries.layer_times(layer_id, query, session)


@router.get("/api/timeseries", response_model=TimeSeriesOutput)
def get_timeseries(query: Annotated[TimeSeriesQuery, Query()], session: SessionDep):
    return timeseries.get_timeseries(query, session)

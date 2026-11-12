from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import AwareDatetime

from app.schemas.common import Page
from app.schemas.runs import RunInput, RunInputSnapshot, RunOutput, RunResult, RunStatus
from app.routers.dependencies import SessionDep
from app.services import runs

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.delete('/{identity}', status_code=204)
def remove_run(identity: str, session: SessionDep):
    return runs.remove_run(identity, session)


@router.post("", response_model=RunOutput, status_code=201)
def submit_run(body: RunInput, request: Request, response: Response, session: SessionDep,
               idempotency_key: Annotated[str | None, Header()] = None):
    result, created = runs.submit_run(body, request.state.trace_id, session, idempotency_key)
    if not created:
        response.status_code = 200
    return result


@router.post("/{identity}/rerun", response_model=RunOutput, status_code=201)
def rerun(identity: str, request: Request, response: Response, session: SessionDep,
          idempotency_key: Annotated[str | None, Header()] = None):
    result, created = runs.rerun(identity, request.state.trace_id, session, idempotency_key)
    if not created:
        response.status_code = 200
    return result


@router.get("", response_model=Page[RunOutput])
def list_runs(session: SessionDep, page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20, scene_id: str | None = None, status: RunStatus | None = None,
    from_time: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_time: Annotated[AwareDatetime | None, Query(alias="to")] = None):
    return runs.list_runs(session, page, page_size, scene_id, status, from_time, to_time)


@router.post("/reconcile")
def reconcile_run_files():
    return runs.reconcile_run_files()


@router.get("/{identity}", response_model=RunOutput)
def get_run(identity: str, session: SessionDep):
    return runs.get_run(identity, session)


@router.post("/{identity}/cancel", response_model=RunOutput)
def cancel_run(identity: str, session: SessionDep):
    return runs.cancel_run(identity, session)


@router.get("/{identity}/input", response_model=RunInputSnapshot)
def get_input(identity: str, session: SessionDep):
    return runs.get_input(identity, session)


@router.get("/{identity}/logs", response_class=PlainTextResponse)
def get_logs(identity: str, session: SessionDep):
    return runs.get_logs(identity, session)


@router.get("/{identity}/result", response_model=RunResult)
def get_result(identity: str, session: SessionDep):
    return runs.get_result(identity, session)


@router.get("/{identity}/download")
def download_result(identity: str, session: SessionDep, format: Literal["json", "geojson"] = "json"):
    return Response(runs.download_result(identity, session, format),
                    media_type="application/geo+json" if format == "geojson" else "application/json",
                    headers={"Content-Disposition": f'attachment; filename="run-{identity}.{format}"'})

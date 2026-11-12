from typing import Annotated

from fastapi import APIRouter, Query

from app.schemas.networks import NetworkOutput, NetworkValidationOutput
from app.schemas.common import Page
from app.routers.dependencies import SessionDep
from app.services import networks

router = APIRouter(prefix="/api/networks", tags=["networks"])


@router.get("", response_model=Page[NetworkOutput])
def list_networks(session: SessionDep, page: Annotated[int, Query(ge=1)] = 1,
                  page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    return networks.list_networks(session, page, page_size)


@router.get("/{identity}", response_model=NetworkOutput)
def get_network(identity: str, session: SessionDep, version: str | None = None):
    return networks.get_network(identity, session, version)


@router.post("/{identity}/validate", response_model=NetworkValidationOutput)
def check_network(identity: str, session: SessionDep, version: str | None = None):
    return networks.check_network(identity, session, version)

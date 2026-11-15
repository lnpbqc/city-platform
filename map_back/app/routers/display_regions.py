from uuid import uuid4

from fastapi import APIRouter
from sqlalchemy import select

from app.errors import ApiProblem
from app.models import DisplayRegion
from app.routers.dependencies import SessionDep
from app.schemas.display_regions import (
    DisplayRegionInput, DisplayRegionName, DisplayRegionOutput, DisplayRegionView,
)

router = APIRouter(prefix="/api/display-regions")


@router.get("", response_model=list[DisplayRegionOutput])
def list_display_regions(session: SessionDep):
    return session.scalars(select(DisplayRegion).order_by(DisplayRegion.id)).all()


@router.post("", response_model=DisplayRegionOutput, status_code=201)
def create_display_region(body: DisplayRegionInput, session: SessionDep):
    region = DisplayRegion(id=str(uuid4()), **body.model_dump())
    session.add(region)
    session.commit()
    session.refresh(region)
    return region


@router.patch("/{region_id}", response_model=DisplayRegionOutput)
def update_display_region(region_id: str, body: DisplayRegionInput | DisplayRegionName | DisplayRegionView,
                          session: SessionDep):
    region = session.get(DisplayRegion, region_id)
    if region is None:
        raise ApiProblem(404, "DISPLAY_REGION_NOT_FOUND", "展示区域不存在")
    for field, value in body.model_dump().items():
        setattr(region, field, value)
    session.commit()
    session.refresh(region)
    return region


@router.delete("/{region_id}", status_code=204)
def delete_display_region(region_id: str, session: SessionDep):
    region = session.get(DisplayRegion, region_id)
    if region is None:
        raise ApiProblem(404, "DISPLAY_REGION_NOT_FOUND", "展示区域不存在")
    session.delete(region)
    session.commit()

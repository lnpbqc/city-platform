from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.cruds import layers as layer_records
from app.schemas.layers import LayerInput, LayerMapStateInput, LayerOutput
from app.schemas.poi import PoiChange
from app.routers.dependencies import SessionDep
from app.services import layers

router = APIRouter()


@router.get("/api/layers", response_model=list[LayerOutput])
def list_layers(session: SessionDep):
    return layer_records.list_layers(session)


@router.post("/api/layers", response_model=LayerOutput, status_code=201)
def create_layer(body: LayerInput, session: SessionDep):
    return layers.create_layer(body, session)


@router.post("/api/layers/upload", response_model=LayerOutput, status_code=201)
async def upload_layer(
    session: SessionDep,
    request: Request,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form(min_length=1, max_length=120)],
    type: Annotated[Literal["geojson", "3dtiles"], Form()],
    category: Annotated[str, Form(min_length=1, max_length=80)] = "自定义图层",
    source: Annotated[str, Form(max_length=500)] = "",
    coordinate_description: Annotated[str, Form(max_length=1000)] = "",
):
    return await layers.publish_layer_upload(request.is_disconnected, file, name, type, category, source, coordinate_description)


@router.put("/api/layers/{layer_id}/poi-data", response_model=LayerOutput)
async def save_poi_snapshot(
    layer_id: str,
    session: SessionDep,
    request: Request,
    file: Annotated[UploadFile, File()],
    asset_id: Annotated[str, Form(min_length=1, max_length=36)],
    version: Annotated[str, Form(min_length=1, max_length=32)],
):
    return await layers.publish_layer_upload(request.is_disconnected, file, "POI", "geojson", "POI", "", "",
                                             poi_target=(layer_id, asset_id, version))


@router.post("/api/layers/{layer_id}/poi-features", response_model=LayerOutput)
async def change_poi(layer_id: str, body: PoiChange, request: Request, session: SessionDep):
    return await layers.change_poi(layer_id, body, request.is_disconnected)


@router.patch("/api/layers/{layer_id}", response_model=LayerOutput)
def update_layer(layer_id: str, body: LayerInput, session: SessionDep):
    return layers.update_layer(layer_id, body, session)


@router.patch("/api/layers/{layer_id}/map-state", response_model=LayerOutput)
def update_layer_map_state(layer_id: str, body: LayerMapStateInput, session: SessionDep):
    return layers.update_layer_map_state(layer_id, body, session)


@router.delete("/api/layers/{layer_id}", status_code=204)
def delete_layer(layer_id: str, session: SessionDep):
    return layers.delete_layer(layer_id, session)

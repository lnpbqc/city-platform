from fastapi import APIRouter

from app.schemas.layers import LayerCatalogOutput
from app.schemas.layers import LayerCatalogStateInput
from app.routers.dependencies import SessionDep
from app.services import layer_catalog
from app.schemas.layers import Campus

router = APIRouter(prefix="/api/layers/catalog", tags=["layers"])


@router.get("", response_model=list[LayerCatalogOutput])
def list_catalog(session: SessionDep, campus: Campus = "university-town"):
    return layer_catalog.list_catalog(session, campus)


@router.patch("/{layer_id}/map-state", response_model=LayerCatalogOutput)
def update_catalog_state(layer_id: str, body: LayerCatalogStateInput, session: SessionDep, campus: Campus = "university-town"):
    return layer_catalog.update_catalog_state(layer_id, body, session, campus)

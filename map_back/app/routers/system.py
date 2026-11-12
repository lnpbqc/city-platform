from fastapi import APIRouter
from fastapi import Request

from app.schemas.common import VersionOutput
from app.services.routing import MODEL_VERSION

router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.get("/api/version", response_model=VersionOutput)
def version(request: Request):
    return {"service_version": request.app.version, "api_version": "1.0", "model_version": MODEL_VERSION, "data_version": "net-001@1.0.0"}

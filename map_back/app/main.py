import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from .database import FILES_DIR, STORAGE_DIR, SessionLocal, get_session
from .assets import asset_for_url, asset_record, bind_asset_version, delete_asset, ensure_initial_version, inventory, lock_catalog, prepare_download, reconcile
from .models import Asset, Bookmark, BuiltinLayerState, Layer, Run
from .schemas import AssetDetail, BookmarkInput, BookmarkOutput, BookmarkRename, LayerInput, LayerMapStateInput, LayerOutput, ReconcileOutput
from .uploads import GEOJSON_LIMIT, ZIP_LIMIT, cleanup, extract_tiles, receive, validate_geojson
from .contracts import VersionOutput
from .errors import ERROR_RESPONSES, ApiProblem, TraceMiddleware, http_error, unexpected_error, validation_error
from .asset_catalog import router as asset_catalog_router
from .asset_queries import router as asset_queries_router
from .builtin_assets import SAMPLES_DIR
from .layer_catalog import initialize_catalog, layer_orderable, router as layer_catalog_router
from .object_index import index_asset, sync_indexes
from .object_queries import router as object_queries_router
from .networks import ensure_networks, router as networks_router
from .scenes import check_version, reserve_writer, scene_record, router as scenes_router
from .routing import MODEL_VERSION
from .runs import router as runs_router
from .run_worker import run_queue
from .timeseries import ensure_timeseries, router as timeseries_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    with SessionLocal() as session:
        await run_in_threadpool(initialize_catalog, session)
        await run_in_threadpool(ensure_timeseries, session)
        await run_in_threadpool(ensure_networks, session)
        session.commit()
    await run_in_threadpool(run_queue.acquire)
    try:
        yield
    finally:
        await run_in_threadpool(run_queue.release)


app = FastAPI(title="城市地图 · 图层服务", version="0.2.0", responses=ERROR_RESPONSES, lifespan=lifespan)
app.add_exception_handler(StarletteHTTPException, http_error)
app.add_exception_handler(RequestValidationError, validation_error)
app.add_exception_handler(Exception, unexpected_error)
app.add_middleware(TraceMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:4173", "http://localhost:4173"], allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "If-Match", "Idempotency-Key"], expose_headers=["X-Trace-ID", "ETag"])
app.mount("/data-files", StaticFiles(directory=FILES_DIR), name="data-files")
app.mount("/samples", StaticFiles(directory=SAMPLES_DIR), name="samples")
app.include_router(asset_catalog_router)
app.include_router(asset_queries_router)
app.include_router(layer_catalog_router)
app.include_router(object_queries_router)
app.include_router(networks_router)
app.include_router(scenes_router)
app.include_router(runs_router)
app.include_router(timeseries_router)
SessionDep = Annotated[Session, Depends(get_session)]


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/version", response_model=VersionOutput)
def version():
    return {"service_version": app.version, "api_version": "1.0", "model_version": MODEL_VERSION, "data_version": "net-001@1.0.0"}


@app.get("/api/layers", response_model=list[LayerOutput])
def list_layers(session: SessionDep):
    return session.scalars(select(Layer).order_by(Layer.created_at.desc())).all()


@app.post("/api/layers", response_model=LayerOutput, status_code=201)
def create_layer(body: LayerInput, session: SessionDep):
    lock_catalog(session)
    asset_id = asset_for_url(session, body.url, body.type)
    layer = Layer(id=str(uuid4()), asset_id=asset_id,
                  asset_version=session.get(Asset, asset_id).current_version if asset_id else None, **body.model_dump())
    layer.map_order = max(99, session.scalar(select(func.max(Layer.map_order))) or 0,
                          session.scalar(select(func.max(BuiltinLayerState.map_order))) or 0) + 1
    layer.orderable = layer_orderable(session, layer)
    if asset_id:
        index_asset(session, session.get(Asset, asset_id))
    session.add(layer)
    session.commit()
    session.refresh(layer)
    return layer


@app.post("/api/layers/upload", response_model=LayerOutput, status_code=201)
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
    identity = str(uuid4())
    temporary = STORAGE_DIR / "tmp" / identity
    published = FILES_DIR / identity
    temporary.mkdir(parents=True)
    try:
        suffix = Path(file.filename or "").suffix.lower()
        if (type == "geojson" and suffix not in (".json", ".geojson")) or (type == "3dtiles" and suffix != ".zip"):
            raise HTTPException(422, "GeoJSON 请上传 .geojson/.json，3D Tiles 请上传 .zip")
        content = temporary / "content"
        content.mkdir()
        if type == "geojson":
            target = content / "data.geojson"
            await receive(file, target, GEOJSON_LIMIT)
            await run_in_threadpool(validate_geojson, target)
        else:
            archive = temporary / "upload.zip"
            await receive(file, archive, ZIP_LIMIT)
            target = await run_in_threadpool(extract_tiles, archive, content)
        relative = target.relative_to(content).as_posix()
        try:
            body = LayerInput(name=name, category=category, type=type, source=source, url=f"/data-files/{identity}/{relative}")
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from error
        if await request.is_disconnected():
            raise HTTPException(400, "上传已取消")
        await run_in_threadpool(shutil.move, str(content), str(published))
        try:
            lock_catalog(session)
            files = inventory(FILES_DIR, identity)
            original_name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1][:255] or None
            asset = Asset(id=identity, original_name=original_name, name=body.name, source=body.source,
                          coordinate_description=coordinate_description.strip() or ("WGS84，经纬度；高程单位：米" if type == "geojson" else ""),
                          type=type, entry_url=body.url, byte_size=sum(item["size"] for item in files),
                          file_count=len(files), uploaded_at=datetime.now(timezone.utc), status="active", error="")
            session.add(asset)
            session.flush()
            ensure_initial_version(session, asset)
            if await request.is_disconnected():
                raise HTTPException(400, "上传已取消")
            return create_layer(body, session)
        except Exception:
            session.rollback()
            await run_in_threadpool(cleanup, published)
            raise
    finally:
        await file.close()
        await run_in_threadpool(cleanup, temporary)


@app.patch("/api/layers/{layer_id}", response_model=LayerOutput)
def update_layer(layer_id: str, body: LayerInput, session: SessionDep):
    lock_catalog(session)
    layer = session.get(Layer, layer_id)
    if layer is None:
        raise HTTPException(404, "图层登记不存在")
    bind_asset_version(session, layer, asset_for_url(session, body.url, body.type), replace=layer.url != body.url)
    resource_changed = layer.url != body.url or layer.type != body.type
    if resource_changed:
        layer.map_attached = False
    for key, value in body.model_dump().items():
        setattr(layer, key, value)
    if resource_changed:
        layer.orderable = layer_orderable(session, layer)
    session.commit()
    session.refresh(layer)
    return layer


@app.patch("/api/layers/{layer_id}/map-state", response_model=LayerOutput)
def update_layer_map_state(layer_id: str, body: LayerMapStateInput, session: SessionDep):
    lock_catalog(session)
    layer = session.get(Layer, layer_id)
    if layer is None:
        raise HTTPException(404, "图层登记不存在")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(layer, key, value)
    session.commit()
    session.refresh(layer)
    return layer


@app.delete("/api/layers/{layer_id}", status_code=204)
def delete_layer(layer_id: str, session: SessionDep):
    lock_catalog(session)
    layer = session.get(Layer, layer_id)
    if layer is None:
        raise HTTPException(404, "图层登记不存在")
    session.delete(layer)
    session.commit()


@app.get("/api/bookmarks", response_model=list[BookmarkOutput])
def list_bookmarks(session: SessionDep):
    return session.scalars(select(Bookmark).order_by(Bookmark.created_at.desc(), Bookmark.id.desc())).all()


@app.post("/api/bookmarks", response_model=BookmarkOutput, status_code=201)
def create_bookmark(body: BookmarkInput, session: SessionDep):
    if body.kind == "scene":
        reserve_writer(session)
        state = body.state
        scene = scene_record(session, state.scene_id)
        check_version(scene, state.scene_version)
        if state.run_id is not None and session.get(Run, state.run_id) is None:
            raise ApiProblem(422, "RUN_NOT_FOUND", "运行记录不存在")
        if scene.document.get("run_id") != state.run_id:
            raise ApiProblem(422, "SCENE_RUN_MISMATCH", "收藏运行与场景保存的运行不一致")
    bookmark = Bookmark(id=str(uuid4()), **body.model_dump(mode="json"))
    session.add(bookmark)
    session.commit()
    session.refresh(bookmark)
    return bookmark


@app.patch("/api/bookmarks/{bookmark_id}", response_model=BookmarkOutput)
def rename_bookmark(bookmark_id: str, body: BookmarkRename, session: SessionDep):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None:
        raise HTTPException(404, "位置收藏不存在")
    bookmark.name = body.name
    session.commit()
    session.refresh(bookmark)
    return bookmark


@app.delete("/api/bookmarks/{bookmark_id}", status_code=204)
def delete_bookmark(bookmark_id: str, session: SessionDep):
    bookmark = session.get(Bookmark, bookmark_id)
    if bookmark is None:
        raise HTTPException(404, "位置收藏不存在")
    session.delete(bookmark)
    session.commit()


@app.post("/api/assets/reconcile", response_model=ReconcileOutput)
def reconcile_assets(session: SessionDep):
    result = reconcile(session)
    sync_indexes(session)
    return result


@app.get("/api/assets/{asset_id}", response_model=AssetDetail)
def get_asset(asset_id: str, session: SessionDep):
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "文件资产不存在")
    return asset_record(session, asset, detail=True)


@app.delete("/api/assets/{asset_id}", status_code=204)
def remove_asset(asset_id: str, session: SessionDep):
    delete_asset(session, asset_id)


@app.get("/api/assets/{asset_id}/download")
def download_asset(asset_id: str, session: SessionDep):
    target, filename, media_type, temporary = prepare_download(session, asset_id)
    return FileResponse(target, filename=filename, media_type=media_type,
                        background=BackgroundTask(shutil.rmtree, temporary))

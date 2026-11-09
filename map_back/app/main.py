import asyncio
from threading import Event, Lock
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
from .poi_mutations import PoiChange, rewrite as rewrite_poi
from .uploads import GEOJSON_LIMIT, ZIP_LIMIT, cleanup, extract_tiles, receive, validate_geojson
from .contracts import VersionOutput
from .errors import ERROR_RESPONSES, ApiProblem, TraceMiddleware, http_error, unexpected_error, validation_error
from .asset_catalog import router as asset_catalog_router
from .asset_queries import router as asset_queries_router
from .builtin_assets import SAMPLES_DIR
from .layer_catalog import initialize_catalog, layer_orderable, router as layer_catalog_router
from .object_index import index_asset, sync_indexes
from .object_queries import router as object_queries_router
from .map_queries import router as map_queries_router
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
app.include_router(map_queries_router)
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
        state = index_asset(session, session.get(Asset, asset_id))
        if session.info.get("upload") and (not state or state.status != "ready"):
            raise HTTPException(422, state.error if state else "对象索引建立失败")
    session.add(layer)
    from .geojson_stream import check_cancel
    check_cancel(None)
    if callback := session.info.get("before_publish"):
        callback()
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
    return await publish_layer_upload(session, request, file, name, type, category, source, coordinate_description)


@app.put("/api/layers/{layer_id}/poi-data", response_model=LayerOutput)
async def save_poi_snapshot(
    layer_id: str,
    session: SessionDep,
    request: Request,
    file: Annotated[UploadFile, File()],
    asset_id: Annotated[str, Form(min_length=1, max_length=36)],
    version: Annotated[str, Form(min_length=1, max_length=32)],
):
    return await publish_layer_upload(session, request, file, "POI", "geojson", "POI", "", "",
                                      poi_target=(layer_id, asset_id, version))


@app.post("/api/layers/{layer_id}/poi-features", response_model=LayerOutput)
async def change_poi(layer_id: str, body: PoiChange, request: Request, session: SessionDep):
    temporary = STORAGE_DIR / "tmp" / str(uuid4())
    temporary.mkdir(parents=True)
    path = temporary / "poi.geojson"
    cancelled = Event()
    async def watch_disconnect():
        while True:
            if await request.is_disconnected():
                cancelled.set()
                return
            await asyncio.sleep(0.1)
    monitor = asyncio.create_task(watch_disconnect())
    def cancel():
        if cancelled.is_set():
            raise HTTPException(400, "上传已取消")
    try:
        def prepare():
            from .geojson_stream import cancellation
            token = cancellation.set(cancel)
            try:
                with SessionLocal() as worker_session:
                    rewrite_poi(worker_session, layer_id, body, path)
            finally:
                cancellation.reset(token)
        await run_in_threadpool(prepare)
        cancel()
        monitor.cancel()
        with path.open("rb") as stream:
            file = UploadFile(stream, filename="poi.geojson")
            return await publish_layer_upload(session, request, file, "POI", "geojson", "POI", "", "",
                                              poi_target=(layer_id, body.asset_id, body.version))
    finally:
        cancelled.set()
        monitor.cancel()
        await run_in_threadpool(cleanup, temporary)


_import_lock = Lock()


async def publish_layer_upload(
    session: Session, request: Request, file: UploadFile, name: str, type: str, category: str,
    source: str, coordinate_description: str, *, poi_target: tuple[str, str, str] | None = None,
):
    identity = str(uuid4())
    temporary = STORAGE_DIR / "tmp" / identity
    published = FILES_DIR / identity
    temporary.mkdir(parents=True)
    cancelled = Event()
    def cancel():
        if cancelled.is_set():
            raise HTTPException(400, "上传已取消")
    def final_cancel():
        from anyio import from_thread
        if from_thread.run(request.is_disconnected):
            cancelled.set()
        cancel()
    async def watch_disconnect():
        while True:
            if await request.is_disconnected():
                cancelled.set()
                return
            await asyncio.sleep(0.1)
    monitor = asyncio.create_task(watch_disconnect())
    try:
        if category.strip() == "POI" and type != "geojson":
            raise HTTPException(422, "POI 图层需要 GeoJSON 点位文件")
        suffix = Path(file.filename or "").suffix.lower()
        if (type == "geojson" and suffix not in (".json", ".geojson")) or (type == "3dtiles" and suffix != ".zip"):
            raise HTTPException(422, "GeoJSON 请上传 .geojson/.json，3D Tiles 请上传 .zip")
        content = temporary / "content"
        content.mkdir()
        target = content / "data.geojson" if type == "geojson" else temporary / "upload.zip"
        await receive(file, target, GEOJSON_LIMIT if type == "geojson" else ZIP_LIMIT, cancel=cancel)
        return await run_in_threadpool(_publish_received, identity, temporary, published, target,
            file.filename, name, type, category, source, coordinate_description, poi_target, cancel, final_cancel)
    finally:
        cancelled.set()
        monitor.cancel()
        await file.close()
        await run_in_threadpool(cleanup, temporary)


def _publish_received(identity, temporary, published, target, filename, name, type, category,
                      source, coordinate_description, poi_target, cancel, final_cancel):
    from .geojson_stream import cancellation
    while not _import_lock.acquire(timeout=0.1):
        cancel()
    token = cancellation.set(cancel)
    try:
        cancel()
        content = temporary / "content"
        if type == "geojson":
            validate_geojson(target, point_only=category.strip() == "POI")
        else:
            target = extract_tiles(target, content)
        relative = target.relative_to(content).as_posix()
        try:
            body = LayerInput(name=name, category=category, type=type, source=source, url=f"/data-files/{identity}/{relative}")
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from error
        cancel()
        shutil.move(str(content), str(published))
        with SessionLocal() as session:
            session.info["upload"] = True
            session.info["before_publish"] = final_cancel
            return LayerOutput.model_validate(_publish_asset(session, body, identity, published, filename, type, coordinate_description, poi_target, cancel))
    finally:
        cancellation.reset(token)
        _import_lock.release()


def _publish_asset(session, body, identity, published, filename, type, coordinate_description, poi_target, cancel):
    try:
        lock_catalog(session)
        layer = None
        if poi_target:
            layer_id, expected_asset, expected_version = poi_target
            layer = session.get(Layer, layer_id)
            if layer is None:
                raise HTTPException(404, "图层登记不存在")
            if (layer.asset_id, layer.asset_version) != (expected_asset, expected_version):
                raise ApiProblem(409, "POI_SNAPSHOT_CONFLICT", "POI 图层已更新，请重新加载后编辑")
            previous = session.get(Asset, expected_asset)
            if (layer.category != "POI" or layer.type != "geojson" or not previous
                    or previous.source_kind != "upload" or previous.protected or previous.status != "active"):
                raise HTTPException(422, "只能编辑本地上传的 POI 图层")
            body.name, body.source = layer.name, layer.source
            coordinate_description = previous.coordinate_description
        files = inventory(FILES_DIR, identity)
        original_name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1][:255] or None
        asset = Asset(id=identity, original_name=original_name, name=body.name, source=body.source,
                      coordinate_description=coordinate_description.strip() or ("WGS84，经纬度；高程单位：米" if type == "geojson" else ""),
                      type=type, entry_url=body.url, byte_size=sum(item["size"] for item in files),
                      file_count=len(files), uploaded_at=datetime.now(timezone.utc), status="active", error="")
        session.add(asset)
        session.flush()
        ensure_initial_version(session, asset)
        cancel()
        if layer is not None:
            state = index_asset(session, asset)
            if not state or state.status != "ready":
                raise HTTPException(422, state.error if state else "对象索引建立失败")
            layer.asset_id, layer.asset_version, layer.url = asset.id, asset.current_version, body.url
            layer.orderable = layer_orderable(session, layer)
            session.flush()
            result = LayerOutput.model_validate(layer)
            cancel()
            session.info["before_publish"]()
            session.commit()
            return result
        return create_layer(body, session)
    except Exception:
        session.rollback()
        cleanup(published)
        raise


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

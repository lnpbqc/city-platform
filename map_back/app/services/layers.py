import asyncio
from threading import Event, Lock
import shutil
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import FILES_DIR, STORAGE_DIR, SessionLocal
from app.services.assets import asset_for_url, bind_asset_version, ensure_initial_version, inventory, lock_catalog
from app.cruds.layers import next_layer_order
from app.models import Asset, Layer
from app.schemas.layers import LayerInput, LayerMapStateInput, LayerOutput
from app.schemas.poi import PoiChange
from app.services.poi_mutations import rewrite as rewrite_poi
from app.services.uploads import GEOJSON_LIMIT, ZIP_LIMIT, cleanup, extract_tiles, receive, validate_geojson
from app.errors import ApiProblem, logger
from app.services.object_index import index_asset
from app.services.rendering import enqueue
from app.services.layer_catalog import layer_orderable

def create_layer(body: LayerInput, session: Session):
    lock_catalog(session)
    asset_id = asset_for_url(session, body.url, body.type)
    layer = Layer(id=str(uuid4()), asset_id=asset_id,
                  asset_version=session.get(Asset, asset_id).current_version if asset_id else None, **body.model_dump())
    layer.map_order = next_layer_order(session)
    layer.orderable = layer_orderable(session, layer)
    if asset_id:
        started = perf_counter()
        state = index_asset(session, session.get(Asset, asset_id))
        if session.info.get("upload"):
            logger.info("upload asset_id=%s stage=object_index duration_ms=%.2f", asset_id, (perf_counter() - started) * 1000)
            if not state or state.status != "ready":
                raise HTTPException(422, state.error if state else "对象索引建立失败")
    session.add(layer)
    if layer.asset_id:
        enqueue(session, layer.asset_id, layer.asset_version, layer.category)
    from app.services.geojson_stream import check_cancel
    check_cancel(None)
    if callback := session.info.get("before_publish"):
        callback()
    session.commit()
    session.refresh(layer)
    return layer


async def change_poi(layer_id: str, body: PoiChange, is_disconnected):
    temporary = STORAGE_DIR / "tmp" / str(uuid4())
    temporary.mkdir(parents=True)
    path = temporary / "poi.geojson"
    cancelled = Event()
    async def watch_disconnect():
        while True:
            if await is_disconnected():
                cancelled.set()
                return
            await asyncio.sleep(0.1)
    monitor = asyncio.create_task(watch_disconnect())
    def cancel():
        if cancelled.is_set():
            raise HTTPException(400, "上传已取消")
    try:
        def prepare():
            from app.services.geojson_stream import cancellation
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
            return await publish_layer_upload(is_disconnected, file, "POI", "geojson", "POI", "", "",
                                              poi_target=(layer_id, body.asset_id, body.version))
    finally:
        cancelled.set()
        monitor.cancel()
        await run_in_threadpool(cleanup, temporary)


_import_lock = Lock()


async def publish_layer_upload(
    is_disconnected, file: UploadFile, name: str, type: str, category: str,
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
        if from_thread.run(is_disconnected):
            cancelled.set()
        cancel()
    async def watch_disconnect():
        while True:
            if await is_disconnected():
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
        started = perf_counter()
        await receive(file, target, GEOJSON_LIMIT if type == "geojson" else ZIP_LIMIT, cancel=cancel)
        logger.info("upload asset_id=%s stage=receive duration_ms=%.2f", identity, (perf_counter() - started) * 1000)
        return await run_in_threadpool(_publish_received, identity, temporary, published, target,
            file.filename, name, type, category, source, coordinate_description, poi_target, cancel, final_cancel)
    finally:
        cancelled.set()
        monitor.cancel()
        await file.close()
        await run_in_threadpool(cleanup, temporary)


def _publish_received(identity, temporary, published, target, filename, name, type, category,
                      source, coordinate_description, poi_target, cancel, final_cancel):
    from app.services.geojson_stream import cancellation
    while not _import_lock.acquire(timeout=0.1):
        cancel()
    token = cancellation.set(cancel)
    try:
        cancel()
        content = temporary / "content"
        started = perf_counter()
        if type == "geojson":
            validate_geojson(target, point_only=category.strip() == "POI")
        else:
            target = extract_tiles(target, content)
        logger.info("upload asset_id=%s stage=validate_or_extract duration_ms=%.2f", identity, (perf_counter() - started) * 1000)
        relative = target.relative_to(content).as_posix()
        try:
            body = LayerInput(name=name, category=category, type=type, source=source, url=f"/data-files/{identity}/{relative}")
        except ValidationError as error:
            raise RequestValidationError(error.errors()) from error
        cancel()
        started = perf_counter()
        shutil.move(str(content), str(published))
        with SessionLocal() as session:
            session.info["upload"] = True
            session.info["before_publish"] = final_cancel
            result = _publish_asset(session, body, identity, published, filename, type, coordinate_description, poi_target, cancel)
            logger.info("upload asset_id=%s stage=publish_total duration_ms=%.2f", identity, (perf_counter() - started) * 1000)
            return LayerOutput.model_validate(result)
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
            started = perf_counter()
            state = index_asset(session, asset)
            logger.info("upload asset_id=%s stage=object_index duration_ms=%.2f", identity, (perf_counter() - started) * 1000)
            if not state or state.status != "ready":
                raise HTTPException(422, state.error if state else "对象索引建立失败")
            layer.asset_id, layer.asset_version, layer.url = asset.id, asset.current_version, body.url
            enqueue(session, layer.asset_id, layer.asset_version, layer.category)
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


def update_layer(layer_id: str, body: LayerInput, session: Session):
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


def update_layer_map_state(layer_id: str, body: LayerMapStateInput, session: Session):
    lock_catalog(session)
    layer = session.get(Layer, layer_id)
    if layer is None:
        raise HTTPException(404, "图层登记不存在")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(layer, key, value)
    session.commit()
    session.refresh(layer)
    return layer


def delete_layer(layer_id: str, session: Session):
    lock_catalog(session)
    layer = session.get(Layer, layer_id)
    if layer is None:
        raise HTTPException(404, "图层登记不存在")
    session.delete(layer)
    session.commit()

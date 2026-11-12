from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import FILES_DIR
from app.errors import ERROR_RESPONSES, TraceMiddleware, http_error, unexpected_error, validation_error
from app.routers import asset_catalog, asset_queries, layer_catalog, object_queries, map_queries, networks, scenes, runs, timeseries, render_api, system, layers, bookmarks, assets
from app.routers.source_files import SourceFiles
from app.services.builtin_assets import SAMPLES_DIR
from app.services.lifecycle import lifespan

app = FastAPI(title="城市地图 · 图层服务", version="0.2.0", responses=ERROR_RESPONSES, lifespan=lifespan)
app.add_exception_handler(StarletteHTTPException, http_error)
app.add_exception_handler(RequestValidationError, validation_error)
app.add_exception_handler(Exception, unexpected_error)
app.add_middleware(TraceMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:4173", "http://localhost:4173"], allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "If-Match", "If-None-Match", "Range", "Idempotency-Key"], expose_headers=["X-Trace-ID", "ETag", "Accept-Ranges", "Content-Range", "Content-Length"])
app.mount("/data-files", SourceFiles(directory=FILES_DIR), name="data-files")
app.mount("/samples", StaticFiles(directory=SAMPLES_DIR), name="samples")
app.include_router(asset_catalog.router)
app.include_router(asset_queries.router)
app.include_router(layer_catalog.router)
app.include_router(object_queries.router)
app.include_router(map_queries.router)
app.include_router(networks.router)
app.include_router(scenes.router)
app.include_router(runs.router)
app.include_router(timeseries.router)
app.include_router(render_api.router)
app.include_router(system.router)
app.include_router(layers.router)
app.include_router(bookmarks.router)
app.include_router(assets.router)

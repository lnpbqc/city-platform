from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.database import SessionLocal
from app.errors import logger
from app.services.run_worker import run_queue
from app.services.rendering import render_queue, recover_retention
from app.services.layer_catalog import initialize_catalog
from app.services.timeseries import ensure_timeseries
from app.services.networks import ensure_networks

@asynccontextmanager
async def lifespan(application: FastAPI):
    started = perf_counter()
    await run_in_threadpool(recover_retention)
    logger.info("startup stage=retention_recovery duration_ms=%.2f", (perf_counter() - started) * 1000)
    with SessionLocal() as session:
        await run_in_threadpool(initialize_catalog, session)
        await run_in_threadpool(ensure_timeseries, session)
        await run_in_threadpool(ensure_networks, session)
        session.commit()
    started = perf_counter()
    await run_in_threadpool(run_queue.acquire)
    logger.info("startup stage=run_recovery duration_ms=%.2f", (perf_counter() - started) * 1000)
    await run_in_threadpool(render_queue.acquire)
    try:
        yield
    finally:
        await run_in_threadpool(render_queue.release)
        await run_in_threadpool(run_queue.release)

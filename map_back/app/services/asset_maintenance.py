from time import perf_counter

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.cruds.layers import ready_geojson_layers
from app.services.assets import asset_record, lock_catalog, reconcile
from app.models import Asset, Layer
from app.errors import logger
from app.services.object_index import sync_indexes
from app.services.layer_catalog import layer_orderable

def reconcile_assets(session: Session):
    started = perf_counter()
    lock_catalog(session)
    ready_layers = ready_geojson_layers()
    published = set(session.execute(ready_layers.with_only_columns(Layer.id, Layer.asset_id, Layer.asset_version)))
    result = reconcile(session)
    sync_indexes(session)
    for layer in session.scalars(ready_layers):
        if (layer.id, layer.asset_id, layer.asset_version) not in published:
            layer.orderable = layer_orderable(session, layer)
    session.commit()
    logger.info("assets stage=full_reconcile discovered=%d duration_ms=%.2f", result["discovered"], (perf_counter() - started) * 1000)
    return result


def get_asset(asset_id: str, session: Session):
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "文件资产不存在")
    return asset_record(session, asset, detail=True)

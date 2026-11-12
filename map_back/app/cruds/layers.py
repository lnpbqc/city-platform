from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BuiltinLayerState, Layer, ObjectIndex


def list_layers(session: Session):
    return session.scalars(select(Layer).order_by(Layer.created_at.desc())).all()


def next_layer_order(session: Session):
    return max(99, session.scalar(select(func.max(Layer.map_order))) or 0,
               session.scalar(select(func.max(BuiltinLayerState.map_order))) or 0) + 1


def ready_geojson_layers():
    return select(Layer).join(ObjectIndex,
        (ObjectIndex.asset_id == Layer.asset_id) & (ObjectIndex.asset_version == Layer.asset_version)
    ).where(Layer.type == "geojson", ObjectIndex.status == "ready")

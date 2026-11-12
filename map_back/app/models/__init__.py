"""Register every mapped class for SQLAlchemy and Alembic."""
from .assets import Asset as Asset, AssetVersion as AssetVersion
from .layers import Layer as Layer, BuiltinLayerState as BuiltinLayerState
from .bookmarks import Bookmark as Bookmark
from .spatial import ObjectIndex as ObjectIndex, SpatialObject as SpatialObject
from .timeseries import TimeSeriesSnapshot as TimeSeriesSnapshot
from .networks import NetworkVersion as NetworkVersion
from .scenes import Scene as Scene, SceneAssetReference as SceneAssetReference
from .runs import Run as Run, RunAssetReference as RunAssetReference
from .geojson import GeoJSONSnapshot as GeoJSONSnapshot, GeoJSONMember as GeoJSONMember
from .render import RenderJob as RenderJob

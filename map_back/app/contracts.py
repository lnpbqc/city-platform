"""数据库无关的 API 1.0 契约；资源接入顺序见 docs/api_contract.md。"""

from datetime import datetime, timezone
from typing import Any, Generic, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


T = TypeVar("T")
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    detail: Any = None
    trace_id: str


class VersionOutput(BaseModel):
    service_version: str
    model_version: str | None
    data_version: str | None
    api_version: str


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class AssetVersionRef(BaseModel):
    asset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class Bounds(BaseModel):
    west: float = Field(ge=-180, le=180, allow_inf_nan=False)
    south: float = Field(ge=-90, le=90, allow_inf_nan=False)
    east: float = Field(ge=-180, le=180, allow_inf_nan=False)
    north: float = Field(ge=-90, le=90, allow_inf_nan=False)
    min_height: float | None = Field(default=None, allow_inf_nan=False)
    max_height: float | None = Field(default=None, allow_inf_nan=False)


class AssetRegisterInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["geojson", "3dtiles", "network"]
    location: str = Field(min_length=1, max_length=2048)
    source: str = Field(default="", max_length=500)
    coordinate_description: str = Field(default="", max_length=1000)


class AssetVersionOutput(AssetVersionRef):
    name: str
    type: Literal["geojson", "3dtiles", "network", "unknown"]
    source_kind: Literal["default", "upload", "external"]
    protected: bool
    source: str
    coordinate_description: str
    entry_url: str | None
    byte_size: int | None = Field(ge=0)
    file_count: int | None = Field(ge=0)
    sha256: str | None
    file_checksums: list[dict] = Field(default_factory=list)
    bounds: Bounds | None
    status: Literal["ready", "missing", "unsafe"]
    created_at: datetime


class Geometry(BaseModel):
    type: Literal["Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection"]
    coordinates: list[Any] | None = None
    geometries: list["Geometry"] | None = None


class ObjectTemporal(BaseModel):
    time: datetime
    resolution: Literal["hour", "day"]
    unit: str
    value: float | None = Field(allow_inf_nan=False)
    missing: bool

    @model_validator(mode="after")
    def missing_matches_value(self):
        if self.missing != (self.value is None):
            raise ValueError("缺测时 value 必须为 null，有值时 missing 必须为 false")
        return self


class ObjectOutput(BaseModel):
    object_id: str
    asset: AssetVersionRef
    layer_id: str | None
    type: str
    name: str | None
    height_m: float | None = Field(default=None, allow_inf_nan=False)
    level: str | None = None
    semantic_source: str
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    coordinates: list[float] | None = None
    geometry: Geometry | None
    properties: dict[str, Any] = Field(default_factory=dict)
    feature_index: int | None = None
    temporal: ObjectTemporal | None = None


class ObjectTypeSummary(BaseModel):
    type: str
    count: int = Field(ge=0)
    area_m2: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    min_height_m: float | None = Field(default=None, allow_inf_nan=False)
    max_height_m: float | None = Field(default=None, allow_inf_nan=False)


class ObjectSummary(BaseModel):
    total: int = Field(ge=0)
    types: list[ObjectTypeSummary]


class LegendItem(BaseModel):
    label: str
    color: str
    value: str | float | None = None


class LayerCatalogOutput(BaseModel):
    id: str
    name: str
    category: Literal["底图", "建筑", "道路", "水体", "专题", "仿真结果"]
    type: str
    asset: AssetVersionRef | None
    url: str | None
    static: bool
    orderable: bool
    object_count: int | None = Field(ge=0)
    unit: str | None
    legend: list[LegendItem] = Field(default_factory=list)
    builtin: bool = False
    campus: str | None = None
    source: str = ""
    map_attached: bool = False
    map_visible: bool = True
    map_opacity: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)
    order: int = Field(default=0, ge=0)


class CameraState(BaseModel):
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    height: float = Field(allow_inf_nan=False)
    heading: float = Field(allow_inf_nan=False)
    pitch: float = Field(allow_inf_nan=False)
    roll: float = Field(allow_inf_nan=False)
    scene_mode: Literal["2d", "3d"]


class SceneLayerState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer_id: str = Field(min_length=1)
    asset: AssetVersionRef | None
    map_attached: bool
    map_visible: bool
    map_opacity: float = Field(ge=0, le=1, allow_inf_nan=False)
    order: int = Field(ge=0)

    @field_validator("layer_id")
    @classmethod
    def layer_identity(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("场景图层ID须非空且无首尾空白")
        return value


class SimulationParams(BaseModel):
    mode: Literal["car"] = "car"


class SceneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    camera: CameraState
    layers: list[SceneLayerState]
    network: AssetVersionRef | None
    origin: str | None
    destination: str | None
    blocked_edges: list[str] = Field(default_factory=list)
    params: SimulationParams = Field(default_factory=SimulationParams)
    seed: int = 0
    current_time: AwareDatetime | None = None
    run_id: str | None = None

    @field_validator("name")
    @classmethod
    def scene_name(cls, value):
        if not value.strip():
            raise ValueError("场景名称不能为空")
        return value.strip()

    @field_validator("current_time")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(timezone.utc) if value else None


class SceneOutput(SceneInput):
    id: str
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class NetworkNode(BaseModel):
    id: str
    coordinates: list[float]


class NetworkEdge(BaseModel):
    id: str
    source: str
    target: str
    length_m: float = Field(gt=0, allow_inf_nan=False)
    speed_mps: float = Field(gt=0, allow_inf_nan=False)


class NetworkOutput(AssetVersionRef):
    name: str
    directed: Literal[False] = False
    crs: str
    synthetic: bool
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]


class NetworkIssue(BaseModel):
    code: str
    message: str
    node_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)


class NetworkValidationOutput(AssetVersionRef):
    valid: bool
    issues: list[NetworkIssue]


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(min_length=1)
    network: AssetVersionRef
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    blocked_edges: list[str] = Field(default_factory=list)
    params: SimulationParams = Field(default_factory=SimulationParams)
    seed: int = 0


class RunInputSnapshot(BaseModel):
    request: RunInput
    scene: SceneOutput
    model_version: str
    data_version: str


class RunOutput(BaseModel):
    run_id: str
    status: RunStatus
    inputs_sha256: str
    model_version: str
    data_version: str
    scene_id: str
    scene_version: int = Field(ge=1)
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    error: ErrorEnvelope | None = None
    trace_id: str


class PathResult(BaseModel):
    path: list[str]
    length_m: float | None = Field(ge=0, allow_inf_nan=False)
    duration_s: float | None = Field(ge=0, allow_inf_nan=False)
    reachable: bool


class RunMetrics(BaseModel):
    increase_percent: float | None = Field(allow_inf_nan=False)
    rerouted: bool


class RunResult(BaseModel):
    run_id: str
    baseline: PathResult
    blocked: PathResult
    metrics: RunMetrics
    created_at: datetime


LayerTimesOutput = list[datetime]


class TimeSeriesValue(BaseModel):
    object_id: str
    geometry: Geometry | None
    value: float | None = Field(allow_inf_nan=False)
    missing: bool

    @model_validator(mode="after")
    def missing_matches_value(self):
        if self.missing != (self.value is None):
            raise ValueError("缺测时 value 必须为 null，有值时 missing 必须为 false")
        return self


class TimeSeriesOutput(BaseModel):
    layer_id: str
    asset: AssetVersionRef
    time: datetime
    resolution: Literal["hour", "day"]
    unit: str
    items: list[TimeSeriesValue]


class StatsOverview(BaseModel):
    asset_count: int = Field(ge=0)
    object_count: int = Field(ge=0)
    run_count: int = Field(ge=0)
    total_byte_size: int = Field(ge=0)
    assets_by_type: dict[str, int]
    assets_added_last_7_days: int = Field(ge=0)

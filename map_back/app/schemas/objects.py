from datetime import datetime
from typing import Any, Literal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.schemas.assets import AssetVersionRef

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


class ObjectFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str | None = Field(default=None, max_length=80)
    version: str | None = Field(default=None, max_length=32)
    layer_id: str | None = Field(default=None, max_length=80)
    type: str | None = Field(default=None, max_length=500)
    q: str | None = Field(default=None, max_length=500)
    bbox: str | None = None
    time: AwareDatetime | None = None
    resolution: Literal["hour", "day"] = "hour"
    campus: Literal["university-town", "huangpu"] = "university-town"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ObjectSelectionInput(ObjectFilters):
    geometry: Geometry

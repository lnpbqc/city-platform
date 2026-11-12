from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.schemas.assets import AssetVersionRef
from app.schemas.objects import Geometry

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


Resolution = Literal["hour", "day"]


class LayerTimeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str | None = Field(default=None, max_length=80)
    version: str | None = Field(default=None, max_length=32)
    campus: Literal["university-town", "huangpu"] = "university-town"


class TimeSeriesQuery(LayerTimeQuery):
    layer_id: str = Field(min_length=1, max_length=80)
    time: AwareDatetime
    resolution: Resolution = "hour"
    bbox: str | None = None

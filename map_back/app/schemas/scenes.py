from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_serializer, field_validator

from app.schemas.assets import AssetVersionRef
from app.schemas.layers import TilesGroundAnchor

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
    name: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    asset: AssetVersionRef | None
    map_attached: bool
    map_visible: bool
    map_opacity: float = Field(ge=0, le=1, allow_inf_nan=False)
    road_max_level: int = Field(default=2, ge=1, le=4, strict=True)
    tiles_height_offset_m: float = Field(default=0, allow_inf_nan=False, strict=True)
    tiles_ground_anchor: TilesGroundAnchor | None = None
    tiles_align_to_terrain: bool | None = Field(default=None, strict=True)
    order: int = Field(ge=0)

    @model_serializer(mode='wrap')
    def serialize_layer(self, handler):
        result = handler(self)
        for key in ('name', 'category'):
            if result.get(key) is None:
                result.pop(key, None)
        if self.tiles_align_to_terrain is None:
            result.pop("tiles_align_to_terrain", None)
            if self.tiles_height_offset_m == 0 and self.tiles_ground_anchor is None:
                result.pop("tiles_height_offset_m", None)
                result.pop("tiles_ground_anchor", None)
        return result

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

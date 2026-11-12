from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.spatial import parse_bbox


class LayerReference(BaseModel):
    model_config = ConfigDict(extra='forbid')
    layer_id: str = Field(min_length=1, max_length=80)
    asset_id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=32)
    campus: Literal['university-town', 'huangpu'] = 'university-town'


class ViewportInput(LayerReference):
    bbox: list[float] = Field(min_length=4, max_length=4)
    width: int = Field(ge=1, le=16384)
    height: int = Field(ge=1, le=16384)
    road_max_level: int = Field(default=2, ge=1, le=4, strict=True)
    meters_per_pixel: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def valid_bbox(self):
        parse_bbox(','.join(map(str, self.bbox)))
        return self


class NearbyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    layers: list[LayerReference] = Field(max_length=100)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    radius_m: float = Field(default=1000, gt=0, le=1000, allow_inf_nan=False)
    limit: int = Field(default=20, ge=1, le=20)


class RoadPickInput(LayerReference):
    object_ids: list[str] = Field(default_factory=list, max_length=2000)
    display_group_id: str | None = Field(default=None, min_length=1, max_length=200)
    render_key: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)

    @model_validator(mode='after')
    def pick_source(self):
        if self.object_ids:
            if self.display_group_id is not None or self.render_key is not None:
                raise ValueError('来源路段与显示道路组须二选一')
        elif self.display_group_id is None or self.render_key is None:
            raise ValueError('需要来源路段或显示道路组及切片版本')
        return self


class RoadGroupsInput(LayerReference):
    render_key: str = Field(pattern=r'^[a-f0-9]{64}$')
    object_ids: list[str] = Field(min_length=1, max_length=2000)

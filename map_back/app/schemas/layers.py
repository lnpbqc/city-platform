from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.assets import AssetVersionRef

class LegendItem(BaseModel):
    label: str
    color: str
    value: str | float | None = None


class TilesGroundAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False, strict=True)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False, strict=True)
    height: float = Field(allow_inf_nan=False, strict=True)


class LayerCatalogOutput(BaseModel):
    render: dict | None = None
    id: str
    name: str
    category: str
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
    road_max_level: int = Field(default=2, ge=1, le=4, strict=True)
    tiles_height_offset_m: float = Field(default=0, allow_inf_nan=False, strict=True)
    tiles_ground_anchor: TilesGroundAnchor | None = None
    tiles_align_to_terrain: bool | None = Field(default=None, strict=True)
    order: int = Field(default=0, ge=0)


class LayerInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="自定义图层", min_length=1, max_length=80)
    type: Literal["geojson", "3dtiles"]
    url: str = Field(min_length=1, max_length=2048)
    source: str = Field(default="", max_length=500)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str):
        parts = urlsplit(value)
        if parts.scheme in ("http", "https") and parts.netloc and not parts.username and not parts.password:
            return value
        if value.startswith(("/data-files/", "/samples/")) and ".." not in parts.path.split("/") and not parts.query and not parts.fragment:
            return value
        raise ValueError("请使用 http(s) 地址或 /data-files/ 文件地址，不支持本机磁盘路径")


class LayerOutput(LayerInput):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    asset_id: str | None
    asset_version: str | None
    asset_source_kind: Literal["default", "upload", "external"] | None
    map_attached: bool
    map_visible: bool
    map_opacity: float
    road_max_level: int = Field(default=2, ge=1, le=4, strict=True)
    tiles_height_offset_m: float = Field(default=0, allow_inf_nan=False, strict=True)
    tiles_ground_anchor: TilesGroundAnchor | None = None
    tiles_align_to_terrain: bool | None = Field(default=None, strict=True)

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class LayerMapStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    map_attached: bool | None = None
    map_visible: bool | None = None
    map_opacity: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    road_max_level: int | None = Field(default=None, ge=1, le=4, strict=True)
    tiles_height_offset_m: float | None = Field(default=None, allow_inf_nan=False, strict=True)
    tiles_ground_anchor: TilesGroundAnchor | None = None
    tiles_align_to_terrain: bool | None = Field(default=None, strict=True)

    @field_validator("map_attached", "map_visible", "map_opacity", "road_max_level", "tiles_height_offset_m")
    @classmethod
    def not_null(cls, value):
        if value is None:
            raise ValueError("图层状态不能为 null")
        return value


class LayerCatalogStateInput(LayerMapStateInput):
    order: int | None = Field(default=None, ge=0)

    @field_validator("order")
    @classmethod
    def order_not_null(cls, value):
        if value is None:
            raise ValueError("顺序不能为 null")
        return value


Campus = Literal["university-town", "huangpu"]

from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.scenes import CameraState

class BookmarkRename(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=120)


def bookmark_utc(value: datetime | None):
    try:
        return value.astimezone(timezone.utc) if value is not None else None
    except (ValueError, OverflowError) as cause:
        raise ValueError("收藏时间超出UTC可表示范围") from cause


class WorkspaceComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time: AwareDatetime
    resolution: Literal["hour", "day"]

    @field_validator("time")
    @classmethod
    def utc_time(cls, value):
        return bookmark_utc(value)


class WorkspaceState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: Literal["map", "simulation"]
    scene_id: str = Field(min_length=1)
    scene_version: int = Field(ge=1)
    run_id: str | None = None
    time: AwareDatetime | None = None
    resolution: Literal["hour", "day"] = "hour"
    camera: CameraState
    comparison: WorkspaceComparison | None = None

    @field_validator("scene_id")
    @classmethod
    def nonempty_scene(cls, value):
        if not value.strip():
            raise ValueError("场景ID不能为空")
        return value

    @field_validator("time")
    @classmethod
    def utc_time(cls, value):
        return bookmark_utc(value)

    @model_validator(mode="after")
    def comparison_matches_page(self):
        if self.page == "simulation" and self.comparison is not None:
            raise ValueError("仿真工作区不支持时间对照")
        return self


class BookmarkInput(BookmarkRename):
    kind: Literal["region", "point", "scene"]
    region_id: str | None = Field(default=None, min_length=1, max_length=80)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    state: WorkspaceState | None = None

    @model_validator(mode="after")
    def location_matches_kind(self):
        if self.kind == "scene":
            if self.state is None or self.region_id is not None or self.longitude is not None or self.latitude is not None:
                raise ValueError("工作区收藏需要有效状态，不能包含地区或点位坐标")
            return self
        if self.state is not None:
            raise ValueError("地区和点位收藏不能包含工作区状态")
        if self.kind == "region":
            if self.region_id is None or self.longitude is not None or self.latitude is not None:
                raise ValueError("地区收藏需要地区代码，不能包含点位坐标")
        elif self.region_id is not None or self.longitude is None or self.latitude is None:
            raise ValueError("点位收藏需要经纬度，不能包含地区代码")
        return self


class BookmarkOutput(BookmarkInput):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def utc_created_at(cls, value: datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

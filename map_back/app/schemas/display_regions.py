from pydantic import BaseModel, ConfigDict, Field

from app.schemas.scenes import CameraState


class DisplayRegionName(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


class DisplayRegionView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera: CameraState
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    radius_m: float = Field(gt=0, lt=25_000, allow_inf_nan=False)


class DisplayRegionInput(DisplayRegionView, DisplayRegionName):
    pass


class DisplayRegionOutput(DisplayRegionInput):
    model_config = ConfigDict(from_attributes=True)
    id: str

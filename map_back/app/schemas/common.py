from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


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


class Bounds(BaseModel):
    west: float = Field(ge=-180, le=180, allow_inf_nan=False)
    south: float = Field(ge=-90, le=90, allow_inf_nan=False)
    east: float = Field(ge=-180, le=180, allow_inf_nan=False)
    north: float = Field(ge=-90, le=90, allow_inf_nan=False)
    min_height: float | None = Field(default=None, allow_inf_nan=False)
    max_height: float | None = Field(default=None, allow_inf_nan=False)

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import Bounds

class AssetVersionRef(BaseModel):
    asset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class AssetRegisterInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal["geojson", "3dtiles", "network"]
    location: str = Field(min_length=1, max_length=2048)
    source: str = Field(default="", max_length=500)
    coordinate_description: str = Field(default="", max_length=1000)


class AssetVersionOutput(AssetVersionRef):
    render: dict | None = None
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


class StatsOverview(BaseModel):
    asset_count: int = Field(ge=0)
    object_count: int = Field(ge=0)
    run_count: int = Field(ge=0)
    total_byte_size: int = Field(ge=0)
    assets_by_type: dict[str, int]
    assets_added_last_7_days: int = Field(ge=0)


class AssetReference(BaseModel):
    id: str
    name: str


class SceneAssetReferenceInfo(AssetReference):
    type: Literal["scene"]
    version: int
    asset_version: str


class RunAssetReferenceInfo(SceneAssetReferenceInfo):
    type: Literal["run"]


class AssetFile(BaseModel):
    path: str
    size: int


class AssetOutput(BaseModel):
    render: dict | None = None
    id: str
    original_name: str | None
    type: Literal["geojson", "3dtiles", "network", "unknown"]
    entry_url: str | None
    byte_size: int | None
    file_count: int | None
    uploaded_at: datetime | None
    discovered_at: datetime
    status: Literal["active", "deleting", "delete_error", "missing", "unsafe"]
    error: str
    references: list[RunAssetReferenceInfo | SceneAssetReferenceInfo | AssetReference]
    reference_count: int
    current_version: str
    source_kind: Literal["default", "upload", "external"]
    protected: bool
    name: str
    source: str
    coordinate_description: str
    sha256: str | None
    bounds: Bounds | None

    @field_validator("uploaded_at", "discovered_at")
    @classmethod
    def utc_times(cls, value: datetime | None):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AssetDetail(AssetOutput):
    files: list[AssetFile]
    file_checksums: list[dict]


class ReconcileOutput(BaseModel):
    assets: list[AssetOutput]
    discovered: int

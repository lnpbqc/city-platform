from typing import Literal

from pydantic import BaseModel, Field, ConfigDict

class PoiChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    asset_id: str = Field(min_length=1, max_length=36)
    version: str = Field(min_length=1, max_length=32)
    operation: Literal['add', 'update', 'delete']
    object_id: str | None = None
    feature: dict | None = None

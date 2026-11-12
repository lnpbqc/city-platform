from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.assets import AssetVersionRef

class NetworkNode(BaseModel):
    id: str
    coordinates: list[float]


class NetworkEdge(BaseModel):
    id: str
    source: str
    target: str
    length_m: float = Field(gt=0, allow_inf_nan=False)
    speed_mps: float = Field(gt=0, allow_inf_nan=False)


class NetworkOutput(AssetVersionRef):
    name: str
    directed: Literal[False] = False
    crs: str
    synthetic: bool
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]


class NetworkIssue(BaseModel):
    code: str
    message: str
    node_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)


class NetworkValidationOutput(AssetVersionRef):
    valid: bool
    issues: list[NetworkIssue]

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.assets import AssetVersionRef
from app.schemas.common import ErrorEnvelope
from app.schemas.scenes import SceneOutput, SimulationParams

RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str = Field(min_length=1)
    network: AssetVersionRef
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    blocked_edges: list[str] = Field(default_factory=list)
    params: SimulationParams = Field(default_factory=SimulationParams)
    seed: int = 0


class RunInputSnapshot(BaseModel):
    request: RunInput
    scene: SceneOutput
    model_version: str
    data_version: str


class RunOutput(BaseModel):
    run_id: str
    status: RunStatus
    inputs_sha256: str
    model_version: str
    data_version: str
    scene_id: str
    scene_version: int = Field(ge=1)
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    error: ErrorEnvelope | None = None
    trace_id: str


class PathResult(BaseModel):
    path: list[str]
    length_m: float | None = Field(ge=0, allow_inf_nan=False)
    duration_s: float | None = Field(ge=0, allow_inf_nan=False)
    reachable: bool


class RunMetrics(BaseModel):
    increase_percent: float | None = Field(allow_inf_nan=False)
    rerouted: bool


class RunResult(BaseModel):
    run_id: str
    baseline: PathResult
    blocked: PathResult
    metrics: RunMetrics
    created_at: datetime

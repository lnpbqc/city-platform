"""Durable run submission, inspection, cancellation and immutable result export."""
from datetime import datetime, timezone
from copy import deepcopy
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import AwareDatetime
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .contracts import Page, RunInput, RunInputSnapshot, RunOutput, RunResult, RunStatus, SceneInput
from .database import get_session
from .errors import ApiProblem
from .models import NetworkVersion, Run, RunAssetReference
from .networks import network_output, network_record
from .routing import MODEL_VERSION
from .run_artifacts import canonical_bytes, publish, reconcile_runs, sync_run
from .run_store import TERMINAL, finish_record, inputs_hash, log_line, run_output, run_record
from .run_worker import run_queue
from .scenes import reserve_writer, scene_document, scene_output, scene_record

router = APIRouter(prefix="/api/runs", tags=["runs"])
SessionDep = Annotated[Session, Depends(get_session)]


def checked_key(value: str | None):
    key = value.strip() if value is not None else None
    if key is not None and not 1 <= len(key) <= 200:
        raise ApiProblem(400, "INVALID_IDEMPOTENCY_KEY", "幂等键长度须为1–200字符")
    return key


def enqueue_snapshot(snapshot: dict, digest: str, references, key, request, response, session):
    existing = session.scalar(select(Run).where(Run.idempotency_key == key)) if key is not None else None
    if existing:
        if existing.inputs_sha256 != digest:
            raise ApiProblem(409, "IDEMPOTENCY_CONFLICT", "同一幂等键已用于不同输入或场景版本")
        response.status_code = 200
        return run_output(existing)
    scene, body = snapshot["scene"], snapshot["request"]
    record = Run(id=str(uuid4()), status="queued", inputs_sha256=digest, model_version=snapshot["model_version"],
        data_version=snapshot["data_version"], scene_id=scene["id"], scene_version=scene["version"],
        network_id=body["network"]["asset_id"], network_version=body["network"]["version"], input_snapshot=snapshot,
        idempotency_key=key, submitted_at=datetime.now(timezone.utc), trace_id=request.state.trace_id, log_text="")
    record.log_text = log_line(record, "queued", "运行已入队")
    session.add(record)
    session.flush()
    session.add_all(RunAssetReference(run_id=record.id, asset_id=asset_id, asset_version=version) for asset_id, version in sorted(references))
    output = run_output(record)
    session.commit()
    sync_run(output.run_id)
    run_queue.wake()
    return output


@router.post("", response_model=RunOutput, status_code=201)
def submit_run(body: RunInput, request: Request, response: Response, session: SessionDep,
               idempotency_key: Annotated[str | None, Header()] = None):
    key = checked_key(idempotency_key)
    reserve_writer(session)
    scene = scene_output(scene_record(session, body.scene_id))
    _, references = scene_document(session, SceneInput.model_validate(scene.model_dump(exclude={"id", "version", "created_at", "updated_at"})))
    network = network_output(network_record(session, body.network.asset_id, body.network.version))
    invalid_nodes = sorted({body.origin, body.destination} - {node.id for node in network.nodes})
    if invalid_nodes:
        raise ApiProblem(422, "INVALID_NODE", "起终点不属于所选路网版本", {"node_ids": invalid_nodes})
    invalid_edges = sorted(set(body.blocked_edges) - {edge.id for edge in network.edges})
    if invalid_edges:
        raise ApiProblem(422, "INVALID_EDGE", "阻断边不属于所选路网版本", {"edge_ids": invalid_edges})
    normalized = body.model_copy(update={"blocked_edges": sorted(set(body.blocked_edges))})
    data_version = f"{body.network.asset_id}@{body.network.version}"
    snapshot = RunInputSnapshot(request=normalized, scene=scene, model_version=MODEL_VERSION, data_version=data_version)
    digest = inputs_hash(snapshot)
    return enqueue_snapshot(snapshot.model_dump(mode="json"), digest, references, key, request, response, session)


@router.post("/{identity}/rerun", response_model=RunOutput, status_code=201)
def rerun(identity: str, request: Request, response: Response, session: SessionDep,
          idempotency_key: Annotated[str | None, Header()] = None):
    key = checked_key(idempotency_key)
    reserve_writer(session)
    source = run_record(session, identity)
    if source.model_version != MODEL_VERSION:
        raise ApiProblem(409, "MODEL_VERSION_UNAVAILABLE", "保存的模型版本当前不可执行")
    references = set(session.execute(select(RunAssetReference.asset_id, RunAssetReference.asset_version)
                                    .where(RunAssetReference.run_id == identity)).all())
    return enqueue_snapshot(deepcopy(source.input_snapshot), source.inputs_sha256, references, key, request, response, session)


@router.get("", response_model=Page[RunOutput])
def list_runs(session: SessionDep, page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20, scene_id: str | None = None, status: RunStatus | None = None,
    from_time: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to_time: Annotated[AwareDatetime | None, Query(alias="to")] = None):
    start = from_time.astimezone(timezone.utc).replace(tzinfo=None) if from_time else None
    end = to_time.astimezone(timezone.utc).replace(tzinfo=None) if to_time else None
    if start and end and start > end:
        raise ApiProblem(422, "VALIDATION_ERROR", "from不能晚于to")
    if session.bind.dialect.name == "sqlite" and not session.in_transaction():
        session.execute(text("BEGIN"))
    filters = []
    if scene_id is not None:
        filters.append(Run.scene_id == scene_id)
    if status:
        filters.append(Run.status == status)
    if start:
        filters.append(Run.submitted_at >= start)
    if end:
        filters.append(Run.submitted_at <= end)
    total = session.scalar(select(func.count()).select_from(Run).where(*filters))
    offset = (page - 1) * page_size
    rows = [] if offset >= total else session.scalars(select(Run).where(*filters).order_by(Run.submitted_at.desc(), Run.id).offset(offset).limit(page_size))
    return {"items": [run_output(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/reconcile")
def reconcile_run_files():
    return reconcile_runs()


@router.get("/{identity}", response_model=RunOutput)
def get_run(identity: str, session: SessionDep):
    return run_output(run_record(session, identity))


@router.post("/{identity}/cancel", response_model=RunOutput)
def cancel_run(identity: str, session: SessionDep):
    reserve_writer(session)
    record = run_record(session, identity)
    if record.status not in TERMINAL:
        run_queue.stop_running(identity)
    return finish_record(session, record, "cancelled", reject_terminal=True)


@router.get("/{identity}/input", response_model=RunInputSnapshot)
def get_input(identity: str, session: SessionDep):
    record = run_record(session, identity)
    sync_run(identity)
    return record.input_snapshot


@router.get("/{identity}/logs", response_class=PlainTextResponse)
def get_logs(identity: str, session: SessionDep):
    return run_record(session, identity).log_text


def result_record(session, identity):
    record = run_record(session, identity)
    if record.status != "succeeded":
        raise ApiProblem(409, "RUN_NOT_SUCCEEDED", "运行尚未成功，当前没有成功结果", {"status": record.status, "error": record.error})
    publish(record, result_only=True)
    return record


@router.get("/{identity}/result", response_model=RunResult)
def get_result(identity: str, session: SessionDep):
    return result_record(session, identity).result


@router.get("/{identity}/download")
def download_result(identity: str, session: SessionDep, format: Literal["json", "geojson"] = "json"):
    record = result_record(session, identity)
    document = record.result
    if format == "geojson":
        network = session.get(NetworkVersion, (record.network_id, record.network_version)).document
        coordinates = {node["id"]: node["coordinates"] for node in network["nodes"]}
        features = []
        for role in ("baseline", "blocked"):
            result = record.result[role]
            points = [coordinates[node] for node in result["path"]]
            geometry = ({"type": "Point", "coordinates": points[0]} if len(points) == 1 else
                        {"type": "LineString", "coordinates": points} if points else None)
            features.append({"type": "Feature", "geometry": geometry, "properties": {"role": role, **result}})
        blocked = set(record.input_snapshot["request"]["blocked_edges"])
        for edge in network["edges"]:
            if edge["id"] in blocked:
                features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [coordinates[edge["source"]], coordinates[edge["target"]]]},
                                 "properties": {"role": "blocked_edge", **edge}})
        document = {"type": "FeatureCollection", "features": features, "run_id": identity,
                    "inputs_sha256": record.inputs_sha256, "model_version": record.model_version, "data_version": record.data_version}
    return Response(canonical_bytes(document), media_type="application/geo+json" if format == "geojson" else "application/json",
                    headers={"Content-Disposition": f'attachment; filename="run-{identity}.{format}"'})

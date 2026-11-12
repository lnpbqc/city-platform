from datetime import datetime, timezone
from copy import deepcopy
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.cruds.runs import run_by_key, run_page, run_references
from app.schemas.runs import RunInput, RunInputSnapshot, RunStatus
from app.schemas.scenes import SceneInput
from app.errors import ApiProblem
from app.models import NetworkVersion, Run, RunAssetReference
from app.services.networks import network_output, network_record
from app.services.routing import MODEL_VERSION
from app.services.run_artifacts import canonical_bytes, publish, reconcile_runs, sync_run
from app.services.run_store import TERMINAL, finish_record, inputs_hash, log_line, run_output, run_record
from app.services.run_worker import run_queue
from app.cruds.transactions import reserve_writer
from app.services.scenes import scene_document, scene_output, scene_record

def remove_run(identity: str, session: Session):
    from app.services.run_artifacts import delete_run
    delete_run(session, identity)


def checked_key(value: str | None):
    key = value.strip() if value is not None else None
    if key is not None and not 1 <= len(key) <= 200:
        raise ApiProblem(400, "INVALID_IDEMPOTENCY_KEY", "幂等键长度须为1–200字符")
    return key


def enqueue_snapshot(snapshot: dict, digest: str, references, key, trace_id, session):
    existing = run_by_key(session, key) if key is not None else None
    if existing:
        if existing.inputs_sha256 != digest:
            raise ApiProblem(409, "IDEMPOTENCY_CONFLICT", "同一幂等键已用于不同输入或场景版本")
        return run_output(existing), False
    scene, body = snapshot["scene"], snapshot["request"]
    record = Run(id=str(uuid4()), status="queued", inputs_sha256=digest, model_version=snapshot["model_version"],
        data_version=snapshot["data_version"], scene_id=scene["id"], scene_version=scene["version"],
        network_id=body["network"]["asset_id"], network_version=body["network"]["version"], input_snapshot=snapshot,
        idempotency_key=key, submitted_at=datetime.now(timezone.utc), trace_id=trace_id, log_text="")
    record.log_text = log_line(record, "queued", "运行已入队")
    session.add(record)
    session.flush()
    session.add_all(RunAssetReference(run_id=record.id, asset_id=asset_id, asset_version=version) for asset_id, version in sorted(references))
    output = run_output(record)
    session.commit()
    sync_run(output.run_id)
    run_queue.wake()
    return output, True


def submit_run(body: RunInput, trace_id: str, session: Session, idempotency_key: str | None):
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
    return enqueue_snapshot(snapshot.model_dump(mode="json"), digest, references, key, trace_id, session)


def rerun(identity: str, trace_id: str, session: Session, idempotency_key: str | None):
    key = checked_key(idempotency_key)
    reserve_writer(session)
    source = run_record(session, identity)
    if source.model_version != MODEL_VERSION:
        raise ApiProblem(409, "MODEL_VERSION_UNAVAILABLE", "保存的模型版本当前不可执行")
    references = run_references(session, identity)
    return enqueue_snapshot(deepcopy(source.input_snapshot), source.inputs_sha256, references, key, trace_id, session)


def list_runs(session: Session, page: int, page_size: int, scene_id: str | None,
              status: RunStatus | None, from_time: AwareDatetime | None, to_time: AwareDatetime | None):
    start = from_time.astimezone(timezone.utc).replace(tzinfo=None) if from_time else None
    end = to_time.astimezone(timezone.utc).replace(tzinfo=None) if to_time else None
    if start and end and start > end:
        raise ApiProblem(422, "VALIDATION_ERROR", "from不能晚于to")
    rows, total = run_page(session, page, page_size, scene_id, status, start, end)
    return {"items": [run_output(row) for row in rows], "total": total, "page": page, "page_size": page_size}


def reconcile_run_files():
    return reconcile_runs()


def get_run(identity: str, session: Session):
    return run_output(run_record(session, identity))


def cancel_run(identity: str, session: Session):
    reserve_writer(session)
    record = run_record(session, identity)
    if record.status not in TERMINAL:
        run_queue.stop_running(identity)
    return finish_record(session, record, "cancelled", reject_terminal=True)


def get_input(identity: str, session: Session):
    record = run_record(session, identity)
    sync_run(identity)
    return record.input_snapshot


def get_logs(identity: str, session: Session):
    return run_record(session, identity).log_text


def result_record(session, identity):
    record = run_record(session, identity)
    if record.status != "succeeded":
        raise ApiProblem(409, "RUN_NOT_SUCCEEDED", "运行尚未成功，当前没有成功结果", {"status": record.status, "error": record.error})
    publish(record, result_only=True)
    return record


def get_result(identity: str, session: Session):
    return result_record(session, identity).result


def download_result(identity: str, session: Session, format: Literal['json', 'geojson']):
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
    return canonical_bytes(document)

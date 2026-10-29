"""Run snapshots, canonical hashes and transactional state transitions."""
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from .contracts import RunInputSnapshot, RunOutput
from .database import SessionLocal
from .errors import ApiProblem
from .models import Run
from .run_artifacts import canonical_bytes, sync_run
from .scenes import reserve_writer

logger = logging.getLogger("city.runs")
TERMINAL = {"succeeded", "failed", "cancelled"}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value is not None else None


def run_output(record: Run):
    return RunOutput(run_id=record.id, status=record.status, inputs_sha256=record.inputs_sha256,
        model_version=record.model_version, data_version=record.data_version, scene_id=record.scene_id,
        scene_version=record.scene_version, submitted_at=utc(record.submitted_at), started_at=utc(record.started_at),
        finished_at=utc(record.finished_at), elapsed_ms=record.elapsed_ms, error=record.error, trace_id=record.trace_id)


def run_record(session, identity):
    record = session.get(Run, identity)
    if record is None:
        raise ApiProblem(404, "RUN_NOT_FOUND", "运行不存在")
    return record


def inputs_hash(snapshot: RunInputSnapshot):
    scene = snapshot.scene.model_dump(mode="json", exclude={"id", "version", "created_at", "updated_at", "run_id"})
    scene["blocked_edges"] = sorted(set(scene["blocked_edges"]))
    scene["layers"] = sorted(scene["layers"], key=lambda layer: (layer["order"], layer["layer_id"]))
    request = snapshot.request.model_dump(mode="json")
    request["blocked_edges"] = sorted(set(request["blocked_edges"]))
    document = {"request": request, "scene_version": snapshot.scene.version,
                "scene": scene, "model_version": snapshot.model_version, "data_version": snapshot.data_version}
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def log_line(record: Run, status: str, message: str):
    return f"{datetime.now(timezone.utc).isoformat()} {status} run_id={record.id} trace_id={record.trace_id} {message}\n"


def claim_next():
    with SessionLocal() as session:
        reserve_writer(session)
        record = session.scalar(select(Run).where(Run.status == "queued").order_by(Run.submitted_at, Run.id).limit(1))
        if record is None:
            return None
        record.status = "running"
        record.started_at = datetime.now(timezone.utc)
        record.log_text += log_line(record, "running", "开始计算")
        identity = record.id
        session.commit()
        return identity


def finish_run(identity: str, status: str, *, result=None, error=None, reject_terminal=False):
    with SessionLocal() as session:
        reserve_writer(session)
        record = run_record(session, identity)
        return finish_record(session, record, status, result=result, error=error, reject_terminal=reject_terminal)


def finish_record(session, record: Run, status: str, *, result=None, error=None, reject_terminal=False):
    if record.status in TERMINAL:
        if reject_terminal:
            raise ApiProblem(409, "RUN_TERMINAL", "运行已结束，终态不能取消", {"status": record.status})
        return run_output(record)
    if record.status == "queued" and status != "cancelled":
        raise ApiProblem(409, "RUN_STATE_CONFLICT", "排队运行须先领取后结束")
    identity = record.id
    record.status = status
    record.finished_at = datetime.now(timezone.utc)
    record.elapsed_ms = max(0, (record.finished_at - utc(record.started_at)).total_seconds() * 1000) if record.started_at else 0
    record.error = {**error, "trace_id": record.trace_id} if error else None
    record.result = result
    record.log_text += log_line(record, status, error["message"] if error else "计算完成" if status == "succeeded" else "取消运行")
    session.flush()
    output = run_output(record)
    session.commit()
    try:
        sync_run(identity)
    except ApiProblem:
        logger.exception("run_id=%s artifact synchronization failed", identity)
    return output


def recover_runs():
    with SessionLocal() as session:
        interrupted = list(session.scalars(select(Run.id).where(Run.status == "running")))
    for identity in interrupted:
        finish_run(identity, "failed", error={"code": "RUN_INTERRUPTED", "message": "服务重启，原运行已中断", "detail": None})

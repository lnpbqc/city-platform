"""Guarded run artifacts mirrored from committed database snapshots."""
import json
import os
import stat
import tempfile
from threading import RLock

from sqlalchemy import select

from .assets import reject_link, valid_identity
from .database import STORAGE_DIR, SessionLocal
from .errors import ApiProblem
from .models import Run

RUNS_DIR = STORAGE_DIR / "runs"
_lock = RLock()


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def run_folder(identity: str):
    if not valid_identity(identity):
        raise ApiProblem(409, "RUN_ARTIFACT_UNSAFE", "运行目录标识无效")
    try:
        reject_link(STORAGE_DIR)
        RUNS_DIR.mkdir(exist_ok=True)
        reject_link(RUNS_DIR)
        folder = RUNS_DIR / identity
        folder.mkdir(exist_ok=True)
        reject_link(folder)
        if not folder.resolve().is_relative_to(RUNS_DIR.resolve()):
            raise ValueError("运行目录越界")
        return folder
    except (OSError, ValueError) as error:
        raise ApiProblem(409, "RUN_ARTIFACT_UNSAFE", "运行目录不可用或含链接", {"run_id": identity}) from error


def _write(folder, name: str, content: bytes, immutable: bool):
    target = folder / name
    try:
        info = reject_link(target)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("运行文件不是常规文件")
        previous = target.read_bytes()
        if previous == content:
            return False
        if immutable:
            raise ApiProblem(409, "RUN_ARTIFACT_CHANGED", "运行输入或结果文件与固定快照不一致", {"file": name})
    except FileNotFoundError:
        pass
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".publish-", delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            try:
                # Publish without replacing an existing immutable file.
                os.link(temporary, target)
            except FileExistsError:
                if target.read_bytes() != content:
                    raise ApiProblem(409, "RUN_ARTIFACT_CHANGED", "运行文件已存在且内容不同", {"file": name})
        else:
            os.replace(temporary, target)
        return True
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def publish(record: Run, *, result_only=False):
    with _lock:
        folder = run_folder(record.id)
        try:
            repaired = int(_write(folder, "input.json", canonical_bytes(record.input_snapshot), True))
            if record.result is not None:
                repaired += int(_write(folder, "result.json", canonical_bytes(record.result), True))
            else:
                try:
                    reject_link(folder / "result.json")
                except FileNotFoundError:
                    pass
                else:
                    raise ApiProblem(409, "ORPHAN_RUN_RESULT", "结果文件没有对应的已提交结果，已保留", {"run_id": record.id})
            if not result_only:
                repaired += int(_write(folder, "run.log", record.log_text.encode("utf-8"), False))
            return repaired
        except (OSError, ValueError) as error:
            raise ApiProblem(409, "RUN_ARTIFACT_UNSAFE", "运行文件不可用或含链接", {"run_id": record.id}) from error


def sync_run(identity: str):
    with _lock, SessionLocal() as session:
        record = session.get(Run, identity)
        if record is None:
            raise ApiProblem(404, "RUN_NOT_FOUND", "运行不存在")
        return publish(record)


def reconcile_runs():
    with SessionLocal() as session:
        identities = list(session.scalars(select(Run.id).order_by(Run.id)))
    repaired = 0
    issues = []
    known = set(identities)
    for identity in identities:
        try:
            repaired += sync_run(identity)
        except ApiProblem as error:
            issues.append({"run_id": identity, "code": error.code, "message": error.message})
    try:
        reject_link(STORAGE_DIR)
        RUNS_DIR.mkdir(exist_ok=True)
        reject_link(RUNS_DIR)
        for entry in RUNS_DIR.iterdir():
            if entry.name not in known:
                issues.append({"run_id": entry.name, "code": "ORPHAN_RUN_DIRECTORY", "message": "目录没有对应运行，已保留"})
    except (OSError, ValueError):
        issues.append({"run_id": None, "code": "RUN_ARTIFACT_UNSAFE", "message": "运行根目录不可用或含链接"})
    return {"checked": len(identities), "repaired_files": repaired, "issues": issues}

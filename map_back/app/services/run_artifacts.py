"""Guarded run artifacts mirrored from committed database snapshots."""
import json
import os
import stat
import tempfile
import shutil
import logging
from threading import RLock

from sqlalchemy import select

from app.services.assets import reject_link, valid_identity
from app.database import STORAGE_DIR, SessionLocal
from app.errors import ApiProblem
from app.models import Run, Scene, Bookmark

RUNS_DIR = STORAGE_DIR / "runs"
_lock = RLock()


def delete_run(session, identity):
    from app.cruds.transactions import reserve_writer
    with _lock:
        reserve_writer(session)
        record = session.get(Run, identity)
        if record is None:
            return
        if record.status not in {'succeeded', 'failed', 'cancelled'}:
            raise ApiProblem(409, 'RUN_NOT_TERMINAL', '请先取消排队或运行中的任务')
        references = [{'type': 'scene', 'id': item.id, 'name': item.document['name']}
                      for item in session.scalars(select(Scene)) if item.document.get('run_id') == identity]
        references.extend({'type': 'bookmark', 'id': item.id, 'name': item.name}
                          for item in session.scalars(select(Bookmark)) if (item.state or {}).get('run_id') == identity)
        if references:
            raise ApiProblem(409, 'RUN_IN_USE', '运行仍被场景或收藏引用，请先解除引用', {'references': references})
        folder = RUNS_DIR / identity
        temporary = None
        recovery_ready = False
        try:
            if folder.exists() or folder.is_symlink():
                reject_link(STORAGE_DIR)
                reject_link(RUNS_DIR)
                reject_link(folder)
                if not valid_identity(identity) or not folder.resolve().is_relative_to(RUNS_DIR.resolve()):
                    raise ValueError('运行目录越界')
                # Validate every member before a directory deletion follows any links.
                for member in folder.rglob('*'):
                    reject_link(member)
                temporary = tempfile.mkdtemp(prefix='.delete-run-', dir=STORAGE_DIR)
                os.replace(folder, os.path.join(temporary, 'snapshot'))
                # Same-volume hard links keep rollback copies without duplicating
                # result contents. Check physical removal before committing SQL.
                shutil.copytree(os.path.join(temporary, 'snapshot'), os.path.join(temporary, 'recovery'), copy_function=os.link)
                recovery_ready = True
                shutil.rmtree(os.path.join(temporary, 'snapshot'))
            session.delete(record)
            session.commit()
        except Exception:
            session.rollback()
            if temporary:
                staged = os.path.join(temporary, 'recovery' if recovery_ready else 'snapshot')
                if os.path.exists(staged):
                    os.replace(staged, folder)
                try:
                    shutil.rmtree(temporary)
                except OSError:
                    logging.getLogger('city.runs').exception('运行删除回滚暂存待清理：%s', temporary)
            raise
        if temporary:
            try:
                shutil.rmtree(temporary)
            except OSError:
                # The committed deletion must not recreate a run. Quarantined
                # artifacts stay outside runs/ and can be retried during startup.
                logging.getLogger('city.runs').exception('运行删除已提交，暂存文件待清理：%s', temporary)


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
        # A result reader can retain an ORM snapshot while another request deletes
        # the run. Check committed existence under the same lock as deletion.
        with SessionLocal() as current:
            if current.scalar(select(Run.id).where(Run.id == record.id)) is None:
                raise ApiProblem(404, 'RUN_NOT_FOUND', '运行不存在')
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
    # Existing records have just been reconstructed from their authoritative SQL
    # snapshots. Any interrupted deletion quarantine is now safe to remove.
    with _lock:
        for entry in STORAGE_DIR.glob('.delete-run-*'):
            try:
                reject_link(entry)
                if not entry.is_dir() or not entry.resolve().is_relative_to(STORAGE_DIR.resolve()):
                    raise ValueError('删除暂存目录无效')
                for member in entry.rglob('*'):
                    reject_link(member)
                shutil.rmtree(entry)
            except (OSError, ValueError):
                issues.append({'run_id': None, 'code': 'RUN_DELETE_CLEANUP_PENDING', 'message': '运行删除暂存文件尚未清理'})
    return {"checked": len(identities), "repaired_files": repaired, "issues": issues}

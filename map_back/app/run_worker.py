"""Single-process durable queue with an isolated, cancellable model process."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Lock, Thread
from time import monotonic
from datetime import datetime, timezone

from .contracts import RunResult
from .database import SessionLocal
from .errors import ApiProblem
from .models import NetworkVersion, Run
from .routing import MODEL_VERSION
from .run_artifacts import canonical_bytes, reconcile_runs, sync_run
from .run_store import claim_next, finish_run, recover_runs
from .scenes import reserve_writer

logger = logging.getLogger("city.runs")
JOB_TIMEOUT_SECONDS = 60.0
PROCESS_ARGS = ["-m", "app.run_compute"]


def spawn_computation():
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "CITY_RUN_PARENT_PID": str(os.getpid())}
    executable = sys.executable
    if os.name == "nt" and os.path.normcase(executable) != os.path.normcase(sys._base_executable):
        # Match CPython multiprocessing's venv launch: bypass the redirector
        # so Popen.pid and kill() refer to the actual calculation process.
        environment["__PYVENV_LAUNCHER__"] = executable
        executable = sys._base_executable
    return subprocess.Popen([executable, *PROCESS_ARGS], cwd=Path(__file__).resolve().parents[1],
        env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def stop_process(process):
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            if process.poll() is None:
                raise
    process.communicate(timeout=3)


class RunQueue:
    def __init__(self):
        self._guard = Lock()
        self._process_guard = Lock()
        self._active = None
        self._users = 0
        self._stop = Event()
        self._wake = Event()
        self._thread = None

    def acquire(self):
        with self._guard:
            if self._users == 0:
                self._stop.clear()
                self._wake.clear()
                recover_runs()
                report = reconcile_runs()
                for issue in report["issues"]:
                    logger.warning("run artifact reconciliation: %s", issue)
                self._thread = Thread(target=self._loop, name="city-run-queue", daemon=True)
                self._thread.start()
            self._users += 1

    def release(self):
        with self._guard:
            self._users -= 1
            if self._users == 0:
                self._stop.set()
                self._wake.set()
                self._thread.join(timeout=5)
                if self._thread.is_alive():
                    raise RuntimeError("运行工作线程未在停止期限内退出")
                self._thread = None

    def wake(self):
        self._wake.set()

    def stop_running(self, identity):
        # Called while holding the database writer, also used to serialize spawn.
        with self._process_guard:
            if self._active is not None and self._active[0] == identity:
                process = self._active[1]
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        if process.poll() is None:
                            raise
                process.wait(timeout=3)

    def _loop(self):
        while not self._stop.is_set():
            identity = None
            try:
                identity = claim_next()
                if identity is not None:
                    self._execute(identity)
                    continue
            except Exception as error:
                logger.exception("run_id=%s worker failure", identity)
                if identity:
                    problem = {"code": error.code, "message": error.message, "detail": error.detail} if isinstance(error, ApiProblem) else {
                        "code": "MODEL_ERROR", "message": "模型执行失败，可通过trace_id查询服务日志", "detail": None}
                    try:
                        finish_run(identity, "failed", error=problem)
                    except Exception:
                        logger.exception("run_id=%s could not persist failure", identity)
            self._wake.wait(0.25)
            self._wake.clear()

    def _execute(self, identity):
        sync_run(identity)
        process = None
        try:
            with SessionLocal() as session:
                reserve_writer(session)
                record = session.get(Run, identity)
                if record.status != "running":
                    return
                if record.model_version != MODEL_VERSION:
                    raise ApiProblem(409, "MODEL_VERSION_UNAVAILABLE", "保存的模型版本当前不可执行")
                network = session.get(NetworkVersion, (record.network_id, record.network_version))
                payload = canonical_bytes({"request": record.input_snapshot["request"], "network": network.document})
                with self._process_guard:
                    process = spawn_computation()
                    self._active = (identity, process)
                session.commit()
            started = monotonic()
            first = True
            while True:
                with SessionLocal() as session:
                    status = session.get(Run, identity).status
                if status != "running":
                    stop_process(process)
                    return
                if self._stop.is_set():
                    raise ApiProblem(409, "SERVICE_STOPPED", "服务停止，运行已中断")
                if monotonic() - started > JOB_TIMEOUT_SECONDS:
                    raise ApiProblem(409, "RUN_TIMEOUT", "模型执行超过60秒时限")
                try:
                    stdout, stderr = process.communicate(input=payload if first else None, timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    first = False
            if stderr:
                logger.error("run_id=%s model stderr: %s", identity, stderr.decode("utf-8", errors="replace")[-8000:])
            if monotonic() - started > JOB_TIMEOUT_SECONDS:
                raise ApiProblem(409, "RUN_TIMEOUT", "模型执行超过60秒时限")
            try:
                output = json.loads(stdout)
            except (ValueError, UnicodeError) as error:
                raise ApiProblem(500, "MODEL_ERROR", "模型进程未返回有效结果") from error
            if "error" in output:
                problem = output["error"]
                raise ApiProblem(422, problem["code"], problem["message"], problem.get("detail"))
            if process.returncode != 0:
                raise ApiProblem(500, "MODEL_ERROR", "模型进程异常退出")
            result = RunResult(run_id=identity, created_at=datetime.now(timezone.utc), **output)
            finish_run(identity, "succeeded", result=result.model_dump(mode="json"))
        finally:
            if process is not None:
                if process.poll() is None:
                    stop_process(process)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
                with self._process_guard:
                    self._active = None


run_queue = RunQueue()

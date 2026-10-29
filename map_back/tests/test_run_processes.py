import os
import time

import pytest

from app import run_worker
from test_runs import setup_run, wait_terminal


def wait_for(predicate, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Expected process event did not occur")


def alive(identity):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, identity)
        if not handle:
            return False
        running = kernel.WaitForSingleObject(handle, 0) == 0x102
        kernel.CloseHandle(handle)
        return running
    try:
        os.kill(identity, 0)
        return True
    except ProcessLookupError:
        return False


@pytest.fixture
def slow_model(monkeypatch, tmp_path):
    pid_file = tmp_path / "actual-pid.txt"
    script = "import os,sys,time;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(30)"
    monkeypatch.setattr(run_worker, "PROCESS_ARGS", ["-c", script, str(pid_file)])
    processes = []
    original = run_worker.spawn_computation

    def spawn():
        process = original()
        processes.append(process)
        return process

    monkeypatch.setattr(run_worker, "spawn_computation", spawn)
    return processes, pid_file


def test_running_cancellation_kills_actual_venv_calculation_process(slow_model, client):
    from sqlalchemy import event
    from app.models import Run

    processes, pid_file = slow_model
    run = client.post("/api/runs", json=setup_run(client)).json()
    wait_for(pid_file.exists)
    identity = int(pid_file.read_text())
    assert identity == processes[0].pid and alive(identity)
    observed = []

    def observe_cancel(record, value, old, initiator):
        if record.id == run["run_id"] and value == "cancelled":
            observed.append(not alive(identity))

    event.listen(Run.status, "set", observe_cancel)
    try:
        cancelled = client.post(f"/api/runs/{run['run_id']}/cancel")
    finally:
        event.remove(Run.status, "set", observe_cancel)
    assert observed == [True], "Cancellation must stop the process before persisting its terminal state"
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    wait_for(lambda: not alive(identity))
    assert client.get(f"/api/runs/{run['run_id']}/result").status_code == 409


def test_timeout_kills_process_and_persists_failure(slow_model, monkeypatch, client):
    processes, pid_file = slow_model
    monkeypatch.setattr(run_worker, "JOB_TIMEOUT_SECONDS", 0.8)
    run = client.post("/api/runs", json=setup_run(client)).json()
    wait_for(pid_file.exists)
    record = wait_terminal(client, run["run_id"])
    assert record["status"] == "failed" and record["error"]["code"] == "RUN_TIMEOUT"
    assert record["error"]["trace_id"] == run["trace_id"]
    assert record["finished_at"] and record["elapsed_ms"] >= 800
    wait_for(lambda: not alive(processes[0].pid))


def test_unexpected_model_process_error_is_sanitized(monkeypatch, client):
    monkeypatch.setattr(run_worker, "PROCESS_ARGS", ["-c", "raise RuntimeError('private-test-detail')"])
    run = client.post("/api/runs", json=setup_run(client)).json()
    record = wait_terminal(client, run["run_id"])
    assert record["status"] == "failed" and record["error"]["code"] == "MODEL_ERROR"
    assert "private-test-detail" not in str(record)
    assert "private-test-detail" not in client.get(f"/api/runs/{run['run_id']}/logs").text


def test_child_exits_when_parent_is_killed(monkeypatch, tmp_path):
    pid_file = tmp_path / "owned-child.txt"
    child_script = "import os,sys,time;from pathlib import Path;from app.parent_lifetime import watch_parent;watch_parent();Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(30)"
    parent_script = "import sys,time;from app import run_worker;run_worker.PROCESS_ARGS=['-c',sys.argv[1],sys.argv[2]];run_worker.spawn_computation();time.sleep(30)"
    monkeypatch.setattr(run_worker, "PROCESS_ARGS", ["-c", parent_script, child_script, str(pid_file)])
    parent = run_worker.spawn_computation()
    identity = None
    try:
        wait_for(pid_file.exists)
        identity = int(pid_file.read_text())
        assert alive(identity)
        parent.kill()
        parent.communicate(timeout=3)
        wait_for(lambda: not alive(identity))
    finally:
        if parent.poll() is None:
            run_worker.stop_process(parent)
        if identity and alive(identity):
            # Only the exact child created by this test is eligible for cleanup.
            os.kill(identity, 9)

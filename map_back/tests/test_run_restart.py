import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Thread

import httpx

from app import run_worker
from test_run_processes import alive, wait_for
from test_runs import setup_run, wait_terminal


def test_service_crash_kills_child_then_recovers_running_and_queued(monkeypatch, tmp_path):
    storage = tmp_path / "service-storage"
    monkeypatch.setenv("MAP_STORAGE_DIR", str(storage))
    monkeypatch.setenv("MAP_DATABASE_URL", "sqlite:///" + (storage / "catalog.db").as_posix())
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    backend = Path(__file__).resolve().parents[1]
    migration = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend,
        env=environment, capture_output=True, timeout=30)
    assert migration.returncode == 0, migration.stderr.decode("utf-8", errors="replace")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    pid_file = tmp_path / "active-calculation.txt"
    child_script = "import os,sys,time;from pathlib import Path;from app.parent_lifetime import watch_parent;watch_parent();Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(30)"
    service_script = "import sys,uvicorn;from app import run_worker;from app.main import app;run_worker.PROCESS_ARGS=['-c',sys.argv[1],sys.argv[2]];uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[3]),log_level='error')"
    monkeypatch.setattr(run_worker, "PROCESS_ARGS", ["-c", service_script, child_script, str(pid_file), str(port)])
    processes = []
    readers = []

    def launch():
        process = run_worker.spawn_computation()
        processes.append(process)
        process.stdin.close()
        for stream in (process.stdout, process.stderr):
            thread = Thread(target=stream.read, daemon=True)
            thread.start()
            readers.append((thread, stream))
        return process

    with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=2) as http:
        def ready():
            try:
                return http.get("/api/health").status_code == 200
            except httpx.TransportError:
                return False

        active_child = None
        try:
            first = launch()
            wait_for(ready, timeout=15)
            body = setup_run(http)
            interrupted = http.post("/api/runs", json=body).json()
            queued = http.post("/api/runs", json={**body, "blocked_edges": []}).json()
            wait_for(pid_file.exists)
            active_child = int(pid_file.read_text())
            assert alive(active_child)
            assert http.get(f"/api/runs/{interrupted['run_id']}").json()["status"] == "running"
            assert http.get(f"/api/runs/{queued['run_id']}").json()["status"] == "queued"
            original_input = (storage / "runs" / interrupted["run_id"] / "input.json").read_bytes()
            first.kill()
            first.wait(timeout=3)
            wait_for(lambda: not alive(active_child))
            monkeypatch.setattr(run_worker, "PROCESS_ARGS", ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"])
            launch()
            wait_for(ready, timeout=15)
            recovered = http.get(f"/api/runs/{interrupted['run_id']}").json()
            assert recovered["status"] == "failed" and recovered["error"]["code"] == "RUN_INTERRUPTED"
            assert recovered["error"]["trace_id"] == interrupted["trace_id"]
            assert recovered["finished_at"] and recovered["inputs_sha256"] == interrupted["inputs_sha256"]
            assert (storage / "runs" / interrupted["run_id"] / "input.json").read_bytes() == original_input
            assert wait_terminal(http, queued["run_id"])["status"] == "succeeded"
            assert http.get(f"/api/runs/{queued['run_id']}/result").json()["blocked"]["length_m"] == 660
            assert http.post(f"/api/runs/{interrupted['run_id']}/cancel").status_code == 409
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)
            for thread, stream in readers:
                thread.join(timeout=2)
                stream.close()
            if active_child and alive(active_child):
                os.kill(active_child, 9)

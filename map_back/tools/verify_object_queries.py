"""Measure loopback TCP queries against 10,000 mixed geometries in isolated storage."""
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep

import httpx
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[2]


def main():
    verification = ROOT / ".verification"
    verification.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="objects-benchmark-", dir=verification) as temporary:
        environment = {**os.environ, "MAP_STORAGE_DIR": temporary,
                       "MAP_DATABASE_URL": "sqlite:///" + (Path(temporary) / "catalog.db").as_posix(),
                       "PYTHONIOENCODING": "utf-8"}
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        migration = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                   cwd=ROOT / "map_back", env=environment, capture_output=True,
                                   text=True, encoding="utf-8", timeout=60, creationflags=creationflags)
        assert migration.returncode == 0, migration.stderr
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"
        features = []
        for index in range(10_000):
            x, y = round(113 + (index % 100) / 1000, 6), round(23 + (index // 100) / 1000, 6)
            end_x, end_y = round(x + 0.0004, 6), round(y + 0.0004, 6)
            geometry = ({"type": "Point", "coordinates": [x, y]},
                        {"type": "LineString", "coordinates": [[x, y], [end_x, end_y]]},
                        {"type": "Polygon", "coordinates": [[[x, y], [end_x, y], [end_x, end_y], [x, end_y], [x, y]]]})[index % 3]
            features.append({"type": "Feature", "properties": {"name": f"object-{index}"}, "geometry": geometry})
        payload = json.dumps({"type": "FeatureCollection", "features": features}).encode()
        measurements = []
        percentiles = []
        server = None
        client = None
        server_log = (Path(temporary) / "server.log").open("w", encoding="utf-8")
        try:
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                       "--port", str(port), "--log-level", "warning", "--no-access-log"],
                                      cwd=ROOT / "map_back", env=environment, stdout=server_log,
                                      stderr=subprocess.STDOUT, creationflags=creationflags)
            client = httpx.Client(base_url=base_url, timeout=60, trust_env=False)
            deadline = perf_counter() + 30
            while True:
                if server.poll() is not None:
                    raise RuntimeError("验收服务启动失败，请检查临时服务日志")
                try:
                    if client.get("/api/health", timeout=0.5).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if perf_counter() >= deadline:
                    raise RuntimeError("验收服务在30秒内未就绪")
                sleep(0.1)
            started = perf_counter()
            response = client.post("/api/layers/upload", data={"name": "万对象混合几何", "type": "geojson"}, files={"file": ("mixed.geojson", payload)})
            assert response.status_code == 201, response.text
            ingestion_ms = (perf_counter() - started) * 1000
            identity = response.json()["asset_id"]
            for label, bbox in (("regional", "113.02,23.02,113.029,23.029"), ("whole_dataset", "-180,-90,180,90")):
                params = {"asset_id": identity, "bbox": bbox, "page_size": 100}
                response = client.get("/api/objects", params=params)
                assert response.status_code == 200, response.text
                warmup = response.json()
                west, south, east, north = map(float, bbox.split(","))
                clipped_count = 0
                for item in warmup["items"]:
                    actual = shape(item["geometry"])
                    left, bottom, right, top = actual.bounds
                    assert west <= left <= right <= east and south <= bottom <= top <= north
                    original = shape(features[item["feature_index"]]["geometry"])
                    if not actual.equals(original):
                        clipped_count += 1
                if label == "regional":
                    assert clipped_count > 0, "区域查询必须实际裁剪跨越边界的线或面"
                durations = []
                for _ in range(100):
                    started = perf_counter()
                    response = client.get("/api/objects", params=params)
                    page = response.json()
                    durations.append((perf_counter() - started) * 1000)
                    assert response.status_code == 200 and len(page["items"]) <= 100
                response = client.get("/api/objects/summary", params=params)
                assert response.status_code == 200, response.text
                summary = response.json()
                assert summary["total"] == page["total"] == sum(item["count"] for item in summary["types"])
                if label == "whole_dataset":
                    assert page["total"] == 10_000
                p95 = sorted(durations)[94]
                percentiles.append(p95)
                measurements.append({"case": label, "bbox": bbox, "requests": 100, "total": page["total"],
                                     "page_size": 100, "clipped_geometries_in_first_page": clipped_count,
                                     "median_ms": round(statistics.median(durations), 2), "p95_ms": round(p95, 2)})
        finally:
            if client is not None:
                client.close()
            if server is not None:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)
            server_log.close()
        report = {"measured_at": datetime.now(timezone.utc).isoformat(), "objects": 10_000,
                  "geometry_types": ["Point", "LineString", "Polygon"], "upload_bytes": len(payload),
                  "ingestion_ms": round(ingestion_ms, 2), "transport": "TCP loopback HTTP/1.1 via persistent httpx.Client",
                  "measurements": measurements}
        (verification / "step08-performance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True))
        assert all(value <= 200 for value in percentiles), measurements


if __name__ == "__main__":
    main()

"""Measure full model calculation on a 100,000-edge long chain with a bypass."""
import json
import platform
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contracts import NetworkOutput
from app.routing import calculate_routes

size = 100_000
nodes = [{"id": f"N{index:06}", "coordinates": [113.36, 23.04]} for index in range(size)]
edges = [{"id": f"E{index}", "source": nodes[index]["id"], "target": nodes[index + 1]["id"], "length_m": 1, "speed_mps": 10}
         for index in range(size - 1)]
edges.append({"id": "bypass", "source": nodes[-3]["id"], "target": nodes[-1]["id"], "length_m": 2.5, "speed_mps": 10})
network = NetworkOutput(asset_id="benchmark", version="1", name="synthetic", crs="EPSG:4326", synthetic=True, nodes=nodes, edges=edges)
measurements = []
for _ in range(3):
    started = perf_counter()
    baseline, blocked, metrics = calculate_routes(network, nodes[0]["id"], nodes[-1]["id"], [f"E{size - 2}"])
    measurements.append((perf_counter() - started) * 1000)
    assert baseline.length_m == size - 1 and len(baseline.path) == size
    assert blocked.length_m == size - 0.5 and len(blocked.path) == size - 1
    assert metrics.rerouted is True
print(json.dumps({"python": platform.python_version(), "platform": platform.platform(), "nodes": size, "edges": len(edges),
                  "includes": ["graph validation", "adjacency construction", "two Dijkstra searches", "lexical path reconstruction", "metrics"],
                  "elapsed_ms": measurements, "max_ms": max(measurements), "threshold_ms": 2000,
                  "passed": max(measurements) <= 2000, "baseline_m": baseline.length_m, "blocked_m": blocked.length_m}))
if max(measurements) > 2000:
    raise SystemExit(1)

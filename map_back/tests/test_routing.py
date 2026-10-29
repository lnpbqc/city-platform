import json
import random
from copy import deepcopy
from pathlib import Path

import pytest

from app.contracts import NetworkOutput
from app.errors import ApiProblem
from app.routing import MODEL_VERSION, calculate_routes


def sample():
    return NetworkOutput.model_validate_json((Path(__file__).parents[1] / "app/data/net-001.json").read_text(encoding="utf-8"))


def graph(edges):
    return NetworkOutput(asset_id="test", version="1", name="test", directed=False, crs="EPSG:4326", synthetic=True,
                         nodes=[{"id": identity, "coordinates": [113, 23]} for identity in sorted({node for edge in edges for node in edge[:2]})],
                         edges=[{"id": f"{source}-{target}", "source": source, "target": target, "length_m": length, "speed_mps": speed}
                                for source, target, length, speed in edges])


def test_net001_baseline_and_blocked_routes_and_metrics():
    baseline, blocked, metrics = calculate_routes(sample(), "S", "T", ["B-T"])
    assert MODEL_VERSION == "dijkstra-undirected-v1"
    assert baseline.model_dump() == {"path": ["S", "A", "B", "T"], "length_m": 660, "duration_s": 66, "reachable": True}
    assert blocked.model_dump() == {"path": ["S", "A", "C", "D", "T"], "length_m": 960, "duration_s": 96, "reachable": True}
    assert metrics.rerouted is True
    assert metrics.increase_percent == pytest.approx(45.45454545454545)
    assert f"{metrics.increase_percent:.1f}" == "45.5"


def test_undirected_reverse_route_and_per_edge_travel_times():
    network = graph([("S", "A", 10, 1), ("A", "T", 20, 10), ("S", "T", 40, 40)])
    baseline, blocked, metrics = calculate_routes(network, "T", "S", [])
    assert baseline.path == ["T", "A", "S"] and baseline.length_m == 30
    assert baseline.duration_s == 12
    assert blocked == baseline and metrics.increase_percent == 0 and metrics.rerouted is False


def test_unreachable_and_same_origin_are_valid_results():
    baseline, blocked, metrics = calculate_routes(sample(), "S", "T", ["S-A"])
    assert baseline.reachable is True
    assert blocked.model_dump() == {"path": [], "length_m": None, "duration_s": None, "reachable": False}
    assert metrics.increase_percent is None and metrics.rerouted is False
    baseline, blocked, metrics = calculate_routes(sample(), "S", "S", ["S-A"])
    assert baseline.model_dump() == {"path": ["S"], "length_m": 0, "duration_s": 0, "reachable": True}
    assert blocked == baseline and metrics.increase_percent is None and metrics.rerouted is False


@pytest.mark.parametrize("origin,destination,edges,code", [("bad", "T", [], "INVALID_NODE"),
    ("S", "bad", [], "INVALID_NODE"), ("S", "T", ["T-B"], "INVALID_EDGE")])
def test_invalid_inputs_are_rejected_before_calculation(origin, destination, edges, code):
    with pytest.raises(ApiProblem) as failure:
        calculate_routes(sample(), origin, destination, edges)
    assert failure.value.status_code == 422 and failure.value.code == code


def test_equal_cost_compares_entire_node_sequence_and_is_input_order_independent():
    network = graph([("S", "A", 1, 1), ("A", "Z", 1, 1), ("Z", "T", 1, 1),
                     ("S", "B", 1, 1), ("B", "C", 1, 1), ("C", "T", 1, 1)])
    expected = ["S", "A", "Z", "T"]
    for seed in range(8):
        random.Random(seed).shuffle(network.edges)
        random.Random(seed + 1).shuffle(network.nodes)
        assert calculate_routes(network, "S", "T", [])[0].path == expected
    baseline, blocked, metrics = calculate_routes(network, "S", "T", ["A-Z"])
    assert blocked.path == ["S", "B", "C", "T"]
    assert metrics.rerouted is True and metrics.increase_percent == 0


def test_equal_decimal_lengths_use_lexical_path_without_an_epsilon_detour():
    network = graph([("S", "A", 0.1, 1), ("A", "T", 0.2, 1), ("S", "T", 0.3, 1)])
    assert calculate_routes(network, "S", "T", [])[0].path == ["S", "A", "T"]
    network.edges[1].length_m = 0.20000000000000004
    assert calculate_routes(network, "S", "T", [])[0].path == ["S", "T"]


def test_blocked_ids_deduplicate_without_mutating_network():
    network = sample()
    before = deepcopy(network.model_dump())
    first = calculate_routes(network, "S", "T", ["B-T", "B-T"])
    assert first == calculate_routes(network, "S", "T", ["B-T"])
    assert network.model_dump() == before
    json.dumps([value.model_dump() for value in first], allow_nan=False)


def test_invalid_graph_and_numeric_overflow_fail_explicitly():
    network = sample()
    network.edges[0].length_m = -1
    with pytest.raises(ApiProblem) as failure:
        calculate_routes(network, "S", "T", [])
    assert failure.value.code == "NETWORK_INVALID"
    network = graph([("S", "A", 1e308, 1), ("A", "T", 1e308, 1)])
    with pytest.raises(ApiProblem) as failure:
        calculate_routes(network, "S", "T", [])
    assert failure.value.code == "NUMERIC_RANGE"
    network = graph([("S", "T", 1e308, 1e-308)])
    with pytest.raises(ApiProblem) as failure:
        calculate_routes(network, "S", "T", [])
    assert failure.value.code == "NUMERIC_RANGE"


def test_very_different_decimal_magnitudes_keep_exact_shortest_path():
    network = graph([("S", "A", 1e20, 1e20), ("A", "T", 1, 1), ("S", "T", 1e20, 1e20)])
    assert calculate_routes(network, "S", "T", [])[0].path == ["S", "T"]

"""Deterministic shortest-length paths on immutable undirected networks."""
import heapq
import math
from decimal import Decimal, localcontext

from .contracts import NetworkOutput, PathResult, RunMetrics
from .errors import ApiProblem
from .networks import validate_network

MODEL_VERSION = "dijkstra-undirected-v1"


def _finite(value):
    if not math.isfinite(value):
        raise ApiProblem(422, "NUMERIC_RANGE", "路径长度、预计时间或增幅超出有限数值范围")
    return value


def _shortest(adjacency, origin: str, destination: str, blocked: set[str]):
    distances = {destination: Decimal(0)}
    pending = [(Decimal(0), destination)]
    while pending:
        distance, node = heapq.heappop(pending)
        if distance != distances[node]:
            continue
        if node == origin:
            break
        for neighbor, identity, length, _speed in adjacency[node]:
            if identity in blocked:
                continue
            candidate = distance + length
            if neighbor not in distances or candidate < distances[neighbor]:
                distances[neighbor] = candidate
                heapq.heappush(pending, (candidate, neighbor))
    if origin not in distances:
        return PathResult(path=[], length_m=None, duration_s=None, reachable=False), None
    path = [origin]
    durations = []
    node = origin
    while node != destination:
        neighbor, _identity, length, speed = next(edge for edge in adjacency[node]
            if edge[1] not in blocked and edge[0] in distances and edge[2] + distances[edge[0]] == distances[node])
        durations.append(float(length) / speed)
        path.append(neighbor)
        node = neighbor
    try:
        duration = math.fsum(durations)
    except OverflowError as error:
        raise ApiProblem(422, "NUMERIC_RANGE", "路径预计时间超出有限数值范围") from error
    return PathResult(path=path, length_m=_finite(float(distances[origin])),
                      duration_s=_finite(duration), reachable=True), distances[origin]


def calculate_routes(network: NetworkOutput, origin: str, destination: str, blocked_edges: list[str]):
    validation = validate_network(network.model_dump())
    if not validation.valid:
        raise ApiProblem(422, "NETWORK_INVALID", "寻路输入路网未通过校验", validation.model_dump())
    nodes = {node.id for node in network.nodes}
    missing_nodes = sorted({origin, destination} - nodes)
    if missing_nodes:
        raise ApiProblem(422, "INVALID_NODE", "起终点不属于路网版本", {"node_ids": missing_nodes})
    blocked = set(blocked_edges)
    missing_edges = sorted(blocked - {edge.id for edge in network.edges})
    if missing_edges:
        raise ApiProblem(422, "INVALID_EDGE", "阻断边不属于路网版本", {"edge_ids": missing_edges})
    lengths = [Decimal(str(edge.length_m)) for edge in network.edges]
    # Keep sums exact across decimal weight scales, including long chains.
    precision = max((length.adjusted() for length in lengths), default=0) - min(
        (length.as_tuple().exponent for length in lengths), default=0) + len(str(len(nodes))) + 2
    with localcontext() as context:
        context.prec = max(34, precision)
        adjacency = {identity: [] for identity in nodes}
        for edge, length in zip(network.edges, lengths):
            adjacency[edge.source].append((edge.target, edge.id, length, edge.speed_mps))
            adjacency[edge.target].append((edge.source, edge.id, length, edge.speed_mps))
        for edges in adjacency.values():
            edges.sort(key=lambda edge: edge[0])
        baseline, base_length = _shortest(adjacency, origin, destination, set())
        blocked_result, blocked_length = _shortest(adjacency, origin, destination, blocked)
        increase = None
        if base_length and blocked_length is not None:
            increase = _finite(float((blocked_length - base_length) / base_length * 100))
        metrics = RunMetrics(increase_percent=increase,
                             rerouted=baseline.reachable and blocked_result.reachable and baseline.path != blocked_result.path)
    return baseline, blocked_result, metrics

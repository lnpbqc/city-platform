from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.errors import ApiProblem
from app.main import app
from app.models import NetworkVersion
from app.networks import ensure_networks, publish_network, validate_network


def network(identity="test-net", version="1.0.0"):
    return {"asset_id": identity, "version": version, "name": "合成路网", "directed": False,
            "crs": "EPSG:4326", "synthetic": True,
            "nodes": [{"id": "A", "coordinates": [113, 23]}, {"id": "B", "coordinates": [113.01, 23]}],
            "edges": [{"id": "A-B", "source": "A", "target": "B", "length_m": 200, "speed_mps": 10}]}


@pytest.fixture
def network_client(client):
    with SessionLocal() as session:
        session.query(NetworkVersion).delete()
        ensure_networks(session)
        session.commit()
    yield client
    with SessionLocal() as session:
        session.query(NetworkVersion).delete()
        session.commit()


def codes(document):
    return {issue.code: issue for issue in validate_network(document).issues}


def test_validation_reports_duplicate_ids_and_reversed_undirected_edges():
    data = network()
    data["nodes"].append(deepcopy(data["nodes"][0]))
    data["edges"].extend([{**data["edges"][0], "source": "B", "target": "A"},
                          {**data["edges"][0], "id": "reverse", "source": "B", "target": "A"}])
    issues = codes(data)
    assert issues["DUPLICATE_NODE_ID"].node_ids == ["A"]
    assert issues["DUPLICATE_EDGE_ID"].edge_ids == ["A-B"]
    assert issues["DUPLICATE_EDGE"].edge_ids == ["A-B", "reverse"]


def test_validation_reports_isolated_nodes_components_and_missing_endpoints():
    data = network()
    data["nodes"].extend([{"id": node, "coordinates": [114, 24]} for node in ["C", "D", "I"]])
    data["edges"].extend([{**data["edges"][0], "id": "C-D", "source": "C", "target": "D"},
                          {**data["edges"][0], "id": "missing", "target": "unknown"}])
    issues = codes(data)
    assert issues["ISOLATED_NODE"].node_ids == ["I"]
    assert issues["DISCONNECTED"].node_ids == ["A", "B", "C", "D", "I"]
    assert issues["MISSING_NODE"].edge_ids == ["missing"]
    assert issues["MISSING_NODE"].node_ids == ["unknown"]


@pytest.mark.parametrize("field,value", [("length_m", 0), ("length_m", -1), ("speed_mps", 0),
                                        ("speed_mps", -5), ("length_m", float("nan")),
                                        ("speed_mps", float("inf")), ("length_m", True)])
def test_invalid_weights_identify_edge(field, value):
    data = network()
    data["edges"][0][field] = value
    assert codes(data)["INVALID_WEIGHT"].edge_ids == ["A-B"]


@pytest.mark.parametrize("coordinates", [[181, 23], [113, 91], [113], [113, 23, 4, 5],
                                         [float("nan"), 23], [True, 23]])
def test_invalid_wgs84_coordinates_identify_node(coordinates):
    data = network()
    data["nodes"][0]["coordinates"] = coordinates
    assert codes(data)["INVALID_COORDINATES"].node_ids == ["A"]


def test_empty_network_self_loops_and_unsupported_metadata():
    data = network()
    data["edges"][0]["target"] = "A"
    assert "SELF_LOOP" in codes(data)
    data["nodes"] = []
    assert "EMPTY_NETWORK" in codes(data)
    data = network()
    data.update(directed=True, crs="EPSG:3857")
    assert {"DIRECTED_UNSUPPORTED", "CRS_UNSUPPORTED"} <= codes(data).keys()


def test_node_edge_identifiers_and_malformed_documents_are_diagnostic():
    data = network()
    data["nodes"][0]["id"] = " "
    assert "INVALID_NODE_ID" in codes(data)
    data = network()
    data["edges"][0]["id"] = ""
    assert "INVALID_EDGE_ID" in codes(data)
    assert "INVALID_DOCUMENT" in codes({"asset_id": "bad", "version": "1"})


def test_publish_is_immutable_idempotent_and_rejects_invalid_network(network_client):
    data = network()
    with SessionLocal() as session:
        publish_network(session, data)
        session.commit()
        publish_network(session, deepcopy(data))
        session.commit()
        assert session.query(NetworkVersion).filter_by(asset_id="test-net").count() == 1
        changed = deepcopy(data)
        changed["edges"][0]["length_m"] = 300
        with pytest.raises(ApiProblem) as conflict:
            publish_network(session, changed)
        assert conflict.value.status_code == 409
        with pytest.raises(IntegrityError, match="路网版本不可修改"):
            session.execute(update(NetworkVersion).where(NetworkVersion.asset_id == "test-net").values(document=changed))
        session.rollback()
        invalid = network("invalid")
        invalid["edges"][0]["speed_mps"] = 0
        with pytest.raises(ApiProblem) as failure:
            publish_network(session, invalid)
        assert failure.value.status_code == 422
        assert session.get(NetworkVersion, ("invalid", "1.0.0")) is None


def test_network_catalog_versions_pagination_and_latest(network_client):
    with SessionLocal() as session:
        for data in [network(), network(version="2.0.0"), network("another")]:
            publish_network(session, data)
        session.commit()
    first = network_client.get("/api/networks?page=1&page_size=2").json()
    second = network_client.get("/api/networks?page=2&page_size=2").json()
    ids = [(row["asset_id"], row["version"]) for row in first["items"] + second["items"]]
    assert first["total"] == second["total"] == len(set(ids)) == 4
    assert network_client.get("/api/networks/test-net").json()["version"] == "2.0.0"
    assert network_client.get("/api/networks/test-net?version=1.0.0").json()["edges"][0]["length_m"] == 200
    assert network_client.get("/api/networks?page=999999999999999999999999").json()["items"] == []
    for query in ["page=0", "page_size=101"]:
        assert network_client.get("/api/networks?" + query).status_code == 422
    for url in ["/api/networks/missing", "/api/networks/test-net?version=missing"]:
        response = network_client.get(url)
        assert response.status_code == 404
        assert response.json()["code"] == "NETWORK_NOT_FOUND"
        assert response.json()["trace_id"] == response.headers["x-trace-id"]


def test_net001_exact_edges_and_startup_snapshot(network_client):
    first = network_client.get("/api/networks/net-001?version=1.0.0").json()
    assert first["synthetic"] is True and first["directed"] is False
    assert {node["id"] for node in first["nodes"]} == {"S", "A", "B", "C", "D", "T"}
    assert {edge["id"]: edge["length_m"] for edge in first["edges"]} == {
        "S-A": 200, "A-B": 200, "B-T": 260, "A-C": 250, "C-D": 260, "D-T": 250}
    assert {edge["speed_mps"] for edge in first["edges"]} == {10}
    response = network_client.post("/api/networks/net-001/validate?version=1.0.0")
    assert response.status_code == 200
    assert response.json() == {"asset_id": "net-001", "version": "1.0.0", "valid": True, "issues": []}
    with TestClient(app) as restarted:
        assert restarted.get("/api/networks/net-001?version=1.0.0").json() == first
    assert network_client.get("/api/version").json()["data_version"] == "net-001@1.0.0"


def test_validate_existing_invalid_snapshot_returns_identifiers(network_client):
    data = network("legacy-invalid")
    data["edges"][0]["target"] = "missing"
    with SessionLocal() as session:
        session.add(NetworkVersion(asset_id=data["asset_id"], version=data["version"], document=data))
        session.commit()
    response = network_client.post("/api/networks/legacy-invalid/validate?version=1.0.0")
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert next(issue for issue in response.json()["issues"] if issue["code"] == "MISSING_NODE")["node_ids"] == ["missing"]
    response = network_client.get("/api/networks/legacy-invalid")
    assert response.status_code == 409
    assert response.json()["code"] == "NETWORK_INVALID"


def test_latest_skips_invalid_snapshot_but_explicit_validation_reports_it(network_client):
    with SessionLocal() as session:
        publish_network(session, network())
        broken = network(version="2.0.0")
        broken["edges"][0]["speed_mps"] = 0
        session.add(NetworkVersion(asset_id="test-net", version="2.0.0", document=broken))
        session.commit()
    assert network_client.get("/api/networks/test-net").json()["version"] == "1.0.0"
    assert network_client.post("/api/networks/test-net/validate?version=2.0.0").json()["valid"] is False


def test_publish_respects_outer_transaction_rollback_after_a_read(network_client):
    with SessionLocal() as session:
        session.query(NetworkVersion).count()
        publish_network(session, network("rolled-back"))
        session.rollback()
    with SessionLocal() as session:
        assert session.get(NetworkVersion, ("rolled-back", "1.0.0")) is None


@pytest.mark.parametrize("same_content", [True, False])
def test_competing_publications_keep_one_immutable_snapshot(network_client, same_content):
    barrier = Barrier(2)

    def publish(length):
        data = network("concurrent")
        data["edges"][0]["length_m"] = length
        with SessionLocal() as session:
            barrier.wait(timeout=5)
            try:
                publish_network(session, data)
                session.commit()
                return 200
            except ApiProblem as failure:
                session.rollback()
                return failure.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish, 200), pool.submit(publish, 200 if same_content else 300)]
        statuses = sorted(future.result(timeout=10) for future in futures)
    assert statuses == ([200, 200] if same_content else [200, 409])
    with SessionLocal() as session:
        assert session.query(NetworkVersion).filter_by(asset_id="concurrent").count() == 1

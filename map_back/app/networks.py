"""Immutable network snapshots and deterministic undirected graph validation."""
import json
import math
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .contracts import NetworkIssue, NetworkOutput, NetworkValidationOutput, Page
from .database import get_session
from .errors import ApiProblem
from .models import NetworkVersion

router = APIRouter(prefix="/api/networks", tags=["networks"])
SessionDep = Annotated[Session, Depends(get_session)]


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_network(document: dict) -> NetworkValidationOutput:
    problems: dict[str, NetworkIssue] = {}

    def issue(code, message, nodes=(), edges=()):
        problem = problems.setdefault(code, NetworkIssue(code=code, message=message))
        problem.node_ids = sorted(set(problem.node_ids).union(nodes))
        problem.edge_ids = sorted(set(problem.edge_ids).union(edges))

    try:
        NetworkOutput.model_validate(document)
    except ValidationError as error:
        # Numeric/coordinate and graph diagnostics below retain the actual IDs.
        if any(not (entry["loc"][:1] in [("directed",)]
                    or (entry["loc"][:1] == ("edges",) and entry["loc"][-1] in ("length_m", "speed_mps"))
                    or (entry["loc"][:1] == ("nodes",) and "coordinates" in entry["loc"])) for entry in error.errors()):
            issue("INVALID_DOCUMENT", "路网结构或必填字段无效")
    if any(not isinstance(document.get(key), str) or not document[key].strip()
           or document[key] != document[key].strip() or len(document[key]) > limit
           for key, limit in (("asset_id", 120), ("version", 32))):
        issue("INVALID_DOCUMENT", "路网标识和版本须为长度有效且无首尾空白的字符串")
    if document.get("directed", False) is not False:
        issue("DIRECTED_UNSUPPORTED", "当前路网模型使用无向边")
    if document.get("crs") != "EPSG:4326":
        issue("CRS_UNSUPPORTED", "路网节点坐标使用EPSG:4326经纬度")
    nodes = document.get("nodes") if isinstance(document.get("nodes"), list) else []
    edges = document.get("edges") if isinstance(document.get("edges"), list) else []
    adjacency: dict[str, set[str]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        identity = node.get("id")
        if not isinstance(identity, str) or not identity.strip() or identity != identity.strip():
            issue("INVALID_NODE_ID", "节点ID须为非空且无首尾空白的字符串")
            continue
        if identity in adjacency:
            issue("DUPLICATE_NODE_ID", "节点ID重复", [identity])
        adjacency.setdefault(identity, set())
        coordinates = node.get("coordinates")
        if (not isinstance(coordinates, list) or len(coordinates) not in (2, 3)
                or not all(finite_number(value) for value in coordinates)
                or not -180 <= coordinates[0] <= 180 or not -90 <= coordinates[1] <= 90):
            issue("INVALID_COORDINATES", "节点须提供有限WGS84经纬度及可选的米制高程", [identity])
    if not adjacency:
        issue("EMPTY_NETWORK", "路网至少需要一个有效节点")
    edge_ids = set()
    pairs: dict[tuple[str, str], str] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        identity = edge.get("id")
        if not isinstance(identity, str) or not identity.strip() or identity != identity.strip():
            issue("INVALID_EDGE_ID", "边ID须为非空且无首尾空白的字符串")
            continue
        if identity in edge_ids:
            issue("DUPLICATE_EDGE_ID", "边ID重复", edges=[identity])
        edge_ids.add(identity)
        if any(not finite_number(edge.get(field)) or edge[field] <= 0 for field in ("length_m", "speed_mps")):
            issue("INVALID_WEIGHT", "边长度和速度须为有限正数，单位分别为m和m/s", edges=[identity])
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        missing = sorted(node for node in {source, target} if node not in adjacency)
        if missing:
            issue("MISSING_NODE", "边引用了不存在的节点", missing, [identity])
            continue
        if source == target:
            issue("SELF_LOOP", "路网边须连接两个不同节点", [source], [identity])
        pair = tuple(sorted((source, target)))
        if pair in pairs:
            issue("DUPLICATE_EDGE", "同一对节点存在重复无向边", edges=[pairs[pair], identity])
        pairs[pair] = identity
        adjacency[source].add(target)
        adjacency[target].add(source)
    isolated = sorted(node for node, neighbors in adjacency.items() if not neighbors)
    if isolated:
        issue("ISOLATED_NODE", "节点未连接任何有效边", isolated)
    visited = set()
    components = 0
    for root in adjacency:
        if root in visited:
            continue
        components += 1
        pending = [root]
        visited.add(root)
        while pending:
            neighbors = adjacency[pending.pop()] - visited
            visited.update(neighbors)
            pending.extend(neighbors)
    if components > 1:
        issue("DISCONNECTED", f"路网包含{components}个连通分量", sorted(adjacency))
    return NetworkValidationOutput(asset_id=str(document.get("asset_id") or "unknown"),
                                   version=str(document.get("version") or "unknown"),
                                   valid=not problems, issues=sorted(problems.values(), key=lambda item: item.code))


def publish_network(session: Session, document: dict):
    validation = validate_network(document)
    if not validation.valid:
        raise ApiProblem(422, "NETWORK_INVALID", "路网校验失败", validation.model_dump())
    canonical = NetworkOutput.model_validate(document).model_dump()
    key = (canonical["asset_id"], canonical["version"])
    if session.bind.dialect.name == "sqlite":
        connection = session.connection()
        # sqlite3 legacy SELECT does not begin a transaction. A bare savepoint
        # would commit on release and escape the caller's later rollback.
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    existing = session.get(NetworkVersion, key)
    if existing is not None:
        if existing.document != canonical:
            raise ApiProblem(409, "NETWORK_VERSION_CONFLICT", "同一路网版本已存在，发布修改须使用新版本")
        return existing
    record = NetworkVersion(asset_id=key[0], version=key[1], document=canonical)
    # A competing startup can publish the same default without overwriting it.
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError:
        session.expire_all()
        existing = session.get(NetworkVersion, key)
        if existing is None or existing.document != canonical:
            raise ApiProblem(409, "NETWORK_VERSION_CONFLICT", "路网版本已由另一请求发布")
        return existing
    return record


def ensure_networks(session: Session):
    document = json.loads((Path(__file__).parent / "data" / "net-001.json").read_text(encoding="utf-8"))
    publish_network(session, document)


def network_record(session: Session, identity: str, version: str | None = None):
    statement = select(NetworkVersion).where(NetworkVersion.asset_id == identity)
    if version is not None:
        statement = statement.where(NetworkVersion.version == version)
    records = session.scalars(statement.order_by(NetworkVersion.created_at.desc(), NetworkVersion.version.desc()))
    newest = None
    for record in records:
        newest = newest or record
        if version is not None or validate_network(record.document).valid:
            return record
    if newest is None:
        raise ApiProblem(404, "NETWORK_NOT_FOUND", "路网或版本不存在")
    return newest


def network_output(record: NetworkVersion):
    validation = validate_network(record.document)
    if not validation.valid:
        raise ApiProblem(409, "NETWORK_INVALID", "该路网版本未通过校验", validation.model_dump())
    return NetworkOutput.model_validate(record.document)


@router.get("", response_model=Page[NetworkOutput])
def list_networks(session: SessionDep, page: Annotated[int, Query(ge=1)] = 1,
                  page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    if session.bind.dialect.name == "sqlite" and not session.in_transaction():
        session.execute(text("BEGIN"))
    total = session.scalar(select(func.count()).select_from(NetworkVersion))
    start = (page - 1) * page_size
    records = [] if start >= total else session.scalars(select(NetworkVersion)
        .order_by(NetworkVersion.asset_id, NetworkVersion.created_at.desc(), NetworkVersion.version.desc())
        .offset(start).limit(page_size))
    return {"items": [network_output(record) for record in records],
            "total": total, "page": page, "page_size": page_size}


@router.get("/{identity}", response_model=NetworkOutput)
def get_network(identity: str, session: SessionDep, version: str | None = None):
    return network_output(network_record(session, identity, version))


@router.post("/{identity}/validate", response_model=NetworkValidationOutput)
def check_network(identity: str, session: SessionDep, version: str | None = None):
    return validate_network(network_record(session, identity, version).document)

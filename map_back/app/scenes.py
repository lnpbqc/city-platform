"""Scene snapshots with fixed version references and optimistic replacement."""
import re
from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from .builtin_assets import BUILTIN_LAYERS, CAMPUS_KEYS, builtin_asset_id
from .contracts import Page, SceneInput, SceneOutput
from .database import get_session
from .errors import ApiProblem
from .models import Asset, AssetVersion, Run, Scene, SceneAssetReference
from .networks import network_output, network_record

router = APIRouter(prefix="/api/scenes", tags=["scenes"])
SessionDep = Annotated[Session, Depends(get_session)]


def reserve_writer(session: Session):
    if session.bind.dialect.name == "sqlite":
        connection = session.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")


def scene_record(session: Session, identity: str):
    record = session.get(Scene, identity)
    if record is None:
        raise ApiProblem(404, "SCENE_NOT_FOUND", "场景不存在")
    return record


def scene_output(record: Scene):
    return SceneOutput(**record.document, id=record.id, version=record.version,
                       created_at=record.created_at.replace(tzinfo=timezone.utc),
                       updated_at=record.updated_at.replace(tzinfo=timezone.utc))


def expected_version(value: str | None):
    if value is None:
        raise ApiProblem(400, "IF_MATCH_REQUIRED", '需要If-Match版本，例如"1"')
    match = re.fullmatch(r'"([1-9][0-9]*)"', value.strip())
    if match is None or len(match[1]) > 19:
        raise ApiProblem(400, "INVALID_IF_MATCH", 'If-Match须为单个带双引号的正整数版本')
    return int(match[1])


def check_version(record: Scene, expected: int):
    if record.version != expected:
        raise ApiProblem(409, "SCENE_VERSION_CONFLICT", "场景已更新，请读取最新版本后再保存", {"current_version": record.version})


def scene_document(session: Session, body: SceneInput):
    seen = set()
    references = set()
    builtin_ids = {layer["id"] for layer in BUILTIN_LAYERS}
    for layer in body.layers:
        if layer.layer_id in seen:
            raise ApiProblem(422, "INVALID_SCENE_LAYERS", "场景图层ID重复", {"layer_id": layer.layer_id})
        seen.add(layer.layer_id)
        if layer.layer_id == "basemap":
            if layer.asset is not None:
                raise ApiProblem(422, "INVALID_SCENE_LAYERS", "底图状态的asset须为null")
            continue
        if layer.asset is None:
            raise ApiProblem(422, "ASSET_VERSION_REQUIRED", "场景图层须固定资产版本", {"layer_id": layer.layer_id})
        reference = layer.asset
        asset = session.get(Asset, reference.asset_id)
        if asset is None or session.get(AssetVersion, (reference.asset_id, reference.version)) is None:
            raise ApiProblem(422, "ASSET_VERSION_NOT_FOUND", "场景引用的资产版本不存在", reference.model_dump())
        if asset.status != "active":
            raise ApiProblem(422, "ASSET_UNAVAILABLE", "场景引用的资产不可用", {**reference.model_dump(), "status": asset.status})
        if layer.layer_id in builtin_ids and reference.asset_id not in {builtin_asset_id(campus, layer.layer_id) for campus in CAMPUS_KEYS}:
            raise ApiProblem(422, "INVALID_SCENE_LAYERS", "默认图层与资产绑定不一致", {"layer_id": layer.layer_id})
        references.add((reference.asset_id, reference.version))
    if body.network:
        try:
            network = network_output(network_record(session, body.network.asset_id, body.network.version))
        except ApiProblem as error:
            raise ApiProblem(422, error.code, error.message, error.detail) from error
        nodes = {node.id for node in network.nodes}
        missing_nodes = sorted({node for node in (body.origin, body.destination) if node is not None} - nodes)
        if missing_nodes:
            raise ApiProblem(422, "INVALID_NODE", "起终点不属于所选路网版本", {"node_ids": missing_nodes})
        missing_edges = sorted(set(body.blocked_edges) - {edge.id for edge in network.edges})
        if missing_edges:
            raise ApiProblem(422, "INVALID_EDGE", "阻断边不属于所选路网版本", {"edge_ids": missing_edges})
    elif body.blocked_edges:
        raise ApiProblem(422, "NETWORK_REQUIRED", "保存阻断边前须选择路网版本")
    if body.run_id is not None and session.get(Run, body.run_id) is None:
        raise ApiProblem(422, "RUN_NOT_FOUND", "运行记录不存在")
    document = body.model_dump(mode="json")
    document["blocked_edges"] = sorted(set(body.blocked_edges))
    return document, references


def replace_references(session: Session, identity: str, references: set[tuple[str, str]]):
    session.execute(delete(SceneAssetReference).where(SceneAssetReference.scene_id == identity))
    session.add_all(SceneAssetReference(scene_id=identity, asset_id=asset_id, asset_version=version)
                    for asset_id, version in sorted(references))


@router.post("", response_model=SceneOutput, status_code=201)
def create_scene(body: SceneInput, response: Response, session: SessionDep):
    reserve_writer(session)
    document, references = scene_document(session, body)
    now = datetime.now(timezone.utc)
    record = Scene(id=str(uuid4()), version=1, document=document,
                   network_id=body.network.asset_id if body.network else None,
                   network_version=body.network.version if body.network else None, created_at=now, updated_at=now)
    session.add(record)
    session.flush()
    replace_references(session, record.id, references)
    output = scene_output(record)
    session.commit()
    response.headers["ETag"] = '"1"'
    return output


@router.get("", response_model=Page[SceneOutput])
def list_scenes(session: SessionDep, page: Annotated[int, Query(ge=1)] = 1,
                page_size: Annotated[int, Query(ge=1, le=100)] = 20):
    if session.bind.dialect.name == "sqlite" and not session.in_transaction():
        session.execute(text("BEGIN"))
    total = session.scalar(select(func.count()).select_from(Scene))
    start = (page - 1) * page_size
    records = [] if start >= total else session.scalars(select(Scene).order_by(Scene.updated_at.desc(), Scene.id)
                                                       .offset(start).limit(page_size))
    return {"items": [scene_output(record) for record in records], "total": total, "page": page, "page_size": page_size}


@router.get("/{identity}", response_model=SceneOutput)
def get_scene(identity: str, response: Response, session: SessionDep,
              version: Annotated[int | None, Query(ge=1)] = None):
    record = scene_record(session, identity)
    if version is not None:
        check_version(record, version)
    response.headers["ETag"] = f'"{record.version}"'
    return scene_output(record)


@router.put("/{identity}", response_model=SceneOutput)
def update_scene(identity: str, body: SceneInput, response: Response, session: SessionDep,
                  if_match: Annotated[str | None, Header()] = None):
    expected = expected_version(if_match)
    reserve_writer(session)
    record = scene_record(session, identity)
    check_version(record, expected)
    document, references = scene_document(session, body)
    result = session.execute(update(Scene).where(Scene.id == identity, Scene.version == expected)
        .values(version=expected + 1, document=document, updated_at=datetime.now(timezone.utc),
                network_id=body.network.asset_id if body.network else None,
                network_version=body.network.version if body.network else None))
    if result.rowcount != 1:
        raise ApiProblem(409, "SCENE_VERSION_CONFLICT", "场景已更新，请读取最新版本后再保存")
    replace_references(session, identity, references)
    output = scene_output(record)
    session.commit()
    response.headers["ETag"] = f'"{expected + 1}"'
    return output


@router.delete("/{identity}", status_code=204)
def delete_scene(identity: str, session: SessionDep, if_match: Annotated[str | None, Header()] = None):
    expected = expected_version(if_match)
    reserve_writer(session)
    check_version(scene_record(session, identity), expected)
    result = session.execute(delete(Scene).where(Scene.id == identity, Scene.version == expected))
    if result.rowcount != 1:
        raise ApiProblem(409, "SCENE_VERSION_CONFLICT", "场景已更新，请读取最新版本后再删除")
    session.commit()

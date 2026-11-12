from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.cruds.bookmarks import scene_is_bookmarked
from app.cruds.scenes import delete_version, replace_references, scene_page, update_version
from app.services.builtin_assets import BUILTIN_LAYERS, CAMPUS_KEYS, builtin_asset_id
from app.schemas.scenes import SceneInput, SceneOutput
from app.errors import ApiProblem
from app.models import Asset, AssetVersion, Run, Scene
from app.services.networks import network_output, network_record
from app.cruds.transactions import reserve_writer

def scene_record(session: Session, identity: str):
    record = session.get(Scene, identity)
    if record is None:
        raise ApiProblem(404, "SCENE_NOT_FOUND", "场景不存在")
    return record


def scene_output(record: Scene):
    return SceneOutput(**record.document, id=record.id, version=record.version,
                       created_at=record.created_at.replace(tzinfo=timezone.utc),
                       updated_at=record.updated_at.replace(tzinfo=timezone.utc))


def check_version(record: Scene, expected: int):
    if record.version != expected:
        raise ApiProblem(409, "SCENE_VERSION_CONFLICT", "场景已更新，请读取最新版本后再保存", {"current_version": record.version})


def scene_document(session: Session, body: SceneInput):
    seen = set()
    references = set()
    builtin_ids = {layer["id"] for layer in BUILTIN_LAYERS}
    document = body.model_dump(mode="json")
    for layer, state in zip(body.layers, document["layers"]):
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
        if asset.type == "3dtiles" and layer.tiles_align_to_terrain is None:
            placement = layer.model_copy(update={"tiles_align_to_terrain": layer.tiles_ground_anchor is not None})
            state.update(placement.model_dump(mode="json"))
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
    document["blocked_edges"] = sorted(set(body.blocked_edges))
    return document, references


def create_scene(body: SceneInput, session: Session):
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
    return output


def list_scenes(session: Session, page: int, page_size: int, q: str):
    records, total = scene_page(session, page, page_size, q)
    return {"items": [scene_output(record) for record in records], "total": total, "page": page, "page_size": page_size}


def get_scene(identity: str, session: Session, version: int | None):
    record = scene_record(session, identity)
    if version is not None:
        check_version(record, version)
    return scene_output(record)


def update_scene(identity: str, body: SceneInput, session: Session, expected: int):
    reserve_writer(session)
    record = scene_record(session, identity)
    check_version(record, expected)
    document, references = scene_document(session, body)
    network_id = body.network.asset_id if body.network else None
    network_version = body.network.version if body.network else None
    if update_version(session, identity, expected, document, network_id, network_version) != 1:
        raise ApiProblem(409, "SCENE_VERSION_CONFLICT", "场景已更新，请读取最新版本后再保存")
    replace_references(session, identity, references)
    output = scene_output(record)
    session.commit()
    return output


def delete_scene(identity: str, session: Session, expected: int):
    reserve_writer(session)
    check_version(scene_record(session, identity), expected)
    if scene_is_bookmarked(session, identity):
        raise ApiProblem(409, "SCENE_BOOKMARKED", "场景仍被收藏，请先在「收藏与链接」中解除收藏")
    if delete_version(session, identity, expected) != 1:
        raise ApiProblem(409, "SCENE_VERSION_CONFLICT", "场景已更新，请读取最新版本后再删除")
    session.commit()

"""Publish calibrated local 3D Tiles in the original asset or as an independent copy."""
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import FILES_DIR, STORAGE_DIR
from app.errors import ApiProblem
from app.models import Asset, AssetVersion, Layer
from app.schemas.assets import TilesCalibrationInput
from app.services.asset_metadata import _tiles_bounds, manifest_digest
from app.services.assets import (
    calibrated_parts, can_calibrate, directory, local_parts, lock_catalog, published_files, reject_link,
    set_calibrated_layer, valid_identity, version_directory, version_file, version_record,
)
from app.services.object_index import index_asset


def temporary_tile_directory(prefix: str) -> Path:
    reject_link(STORAGE_DIR)
    temporary = STORAGE_DIR / "tmp"
    temporary.mkdir(exist_ok=True)
    reject_link(temporary)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=temporary))


def _current(session, asset_id, body):
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise ApiProblem(404, "ASSET_NOT_FOUND", "文件资产不存在")
    if not can_calibrate(asset):
        raise ApiProblem(422, "TILES_CALIBRATION_UNSUPPORTED", "只能校准可用的本地上传 3D Tiles 模型")
    version = session.get(AssetVersion, (asset_id, asset.current_version))
    if (asset.current_version != body.base_version or
            (version and version.revision != body.base_revision)):
        raise ApiProblem(409, "ASSET_VERSION_CONFLICT", "模型已更新，请重新加载后校准",
                         {"current_version": asset.current_version, "revision": version.revision if version else None})
    if not version or not version.file_manifest or not version.entry_url:
        raise ApiProblem(409, "TILES_SOURCE_UNAVAILABLE", "模型缺少可校准的目录或文件清单")
    local = local_parts(version.entry_url)
    legacy = calibrated_parts(version.entry_url) if not local else None
    if not ((local and local[0] == asset_id) or
            (legacy and legacy[:2] == (asset_id, version.version) and version.tiles_calibrated)):
        raise ApiProblem(409, "TILES_SOURCE_UNAVAILABLE", "模型入口与当前资产版本不一致")
    return asset, version


def _stage(root, files, body, rewritten, staged):
    manifest = []
    for path, record in sorted(files.items()):
        payload = rewritten.get(path)
        if payload is None:
            if body.mode == "copy":
                target = staged / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(version_file(root, path), target)
                with target.open("rb") as model_file:
                    if hashlib.file_digest(model_file, "sha256").hexdigest() != record["sha256"]:
                        raise ApiProblem(409, "ASSET_CONTENT_CHANGED", f"模型文件与资产校验不一致：{path}")
            manifest.append(record)
        else:
            target = staged / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            manifest.append({"path": path, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    return manifest


def _journal(work, **data):
    temporary = work / "pending.next"
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(work / "pending.json")


def _restore_manifests(work, root, paths):
    for relative in paths:
        backup = version_file(work / "backup", relative)
        # Keep the backups until recovery completes so recovery is safe to retry.
        replacement = work / "restore"
        replacement.unlink(missing_ok=True)
        os.link(backup, replacement, follow_symlinks=False)
        replacement.replace(version_file(root, relative))


def recover_tiles_publications(session: Session):
    temporary = STORAGE_DIR / "tmp"
    if not temporary.exists():
        return
    reject_link(temporary)
    lock_catalog(session)
    for work in temporary.glob("tiles-publish-*"):
        reject_link(work)
        journal = work / "pending.json"
        if not journal.exists():
            continue
        reject_link(journal)
        data = json.loads(journal.read_text(encoding="utf-8"))
        identity = data["asset_id"]
        if not valid_identity(identity):
            raise ValueError("资产校准恢复目录无效")
        if data["mode"] == "copy":
            if session.get(Asset, identity) is None and (FILES_DIR / identity).exists():
                shutil.rmtree(directory(FILES_DIR, identity))
        else:
            current = session.get(AssetVersion, (identity, data["version"]))
            if current and current.revision < data["revision"]:
                legacy = calibrated_parts(current.entry_url) if current.entry_url else None
                root = version_directory(identity, current.version) if legacy else directory(FILES_DIR, identity)
                _restore_manifests(work, root, data["paths"])
        shutil.rmtree(work)


def publish_calibration(session: Session, asset_id: str, body: TilesCalibrationInput):
    from app.services.tiles_calibration_geometry import rewrite_tilesets, validate_matrix

    work = None
    discard_work = True
    try:
        asset, version = _current(session, asset_id, body)
        transform = validate_matrix(body.matrix)
        source, files, entry = published_files(asset, version.entry_url)
        prior = {item["path"]: item for item in version.file_manifest}
        if {item["path"]: item["size"] for item in files} != {path: item["size"] for path, item in prior.items()}:
            raise ApiProblem(409, "ASSET_CONTENT_CHANGED", "模型文件与当前资产清单不一致，请检查存储")

        def read(path):
            if path not in prior:
                raise ValueError(f"缺少模型清单 {path}")
            payload = version_file(source, path).read_bytes()
            if hashlib.sha256(payload).hexdigest() != prior[path]["sha256"]:
                raise ApiProblem(409, "ASSET_CONTENT_CHANGED", f"模型清单与当前资产校验不一致：{path}")
            return payload

        session.rollback()
        rewritten = rewrite_tilesets(entry, read, transform)
        if entry not in rewritten or not rewritten.keys() <= prior.keys():
            raise ValueError("不能生成完整的校准清单")
        bounds = _tiles_bounds(json.loads(rewritten[entry]))
        if bounds is None:
            raise ValueError("校准后的模型缺少有效的 WGS84 范围")
        work = temporary_tile_directory("tiles-publish-")
        staged = work / "staged"
        manifest = _stage(source, prior, body, rewritten, staged)
        size = sum(item["size"] for item in manifest)

        lock_catalog(session)
        asset, version = _current(session, asset_id, body)
        copying = body.mode == "copy"
        copied_dir = None
        paths = sorted(rewritten)
        if copying:
            copied_id = str(uuid4())
            destination = FILES_DIR / copied_id
            if destination.exists():
                raise FileExistsError("新资产目录已存在")
            name = body.name.strip()
            asset = Asset(id=copied_id, name=name, original_name=f"{name}.zip", type="3dtiles",
                          source_kind="upload", source=asset.source, coordinate_description=asset.coordinate_description,
                          entry_url=f"/data-files/{copied_id}/{quote(entry)}", current_version="1.0.0",
                          byte_size=size, file_count=len(manifest), uploaded_at=datetime.now(timezone.utc))
            version = AssetVersion(asset_id=asset.id, version=asset.current_version, entry_url=asset.entry_url,
                                   byte_size=size, file_count=len(manifest), revision=0)
            session.add(asset)
            session.flush()
            session.add(version)
            _journal(work, mode=body.mode, asset_id=asset.id)
        else:
            for relative in paths:
                old = version_file(source, relative)
                backup = work / "backup" / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.link(old, backup, follow_symlinks=False)
            _journal(work, mode=body.mode, asset_id=asset.id, version=version.version,
                     revision=version.revision + 1, paths=paths)
        try:
            if copying:
                staged.rename(destination)
                copied_dir = destination
            else:
                for relative in paths:
                    (staged / relative).replace(version_file(source, relative))

            version.revision += 1
            version.byte_size, version.file_count = size, len(manifest)
            version.file_manifest, version.sha256, version.bounds = manifest, manifest_digest(manifest), bounds
            version.tiles_calibrated = True
            version.tiles_terrain_anchor = body.terrain_anchor.model_dump()
            asset.byte_size, asset.file_count = size, len(manifest)
            session.flush()
            if not copying:
                for layer in session.scalars(select(Layer).where(Layer.asset_id == asset_id,
                                                                 Layer.asset_version == version.version)):
                    set_calibrated_layer(layer, version)
            state = index_asset(session, asset, version)
            if not state or state.status != "ready":
                raise ApiProblem(409, "TILES_INDEX_FAILED", "校准模型的索引生成失败")
            session.commit()
        except Exception:
            discard_work = False
            if copied_dir:
                shutil.rmtree(directory(FILES_DIR, asset.id))
            if not copying:
                _restore_manifests(work, source, paths)
            discard_work = True
            raise
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ApiProblem(422, "TILES_CALIBRATION_INVALID", str(error)) from error
    except OSError as error:
        raise ApiProblem(409, "TILES_STORAGE_ERROR", "无法读取或更新校准文件，请检查存储空间及文件权限") from error
    finally:
        session.rollback()
        if work and discard_work:
            shutil.rmtree(work, ignore_errors=True)
    return version_record(asset, version)


def get_calibrated_file(session: Session, asset_id: str, version: str, relative: str):
    marker = session.scalar(select(AssetVersion.tiles_calibrated).join(Asset)
                            .where(AssetVersion.asset_id == asset_id, AssetVersion.version == version,
                                   Asset.status == "active"))
    if not marker:
        raise ApiProblem(404, "TILES_VERSION_NOT_FOUND", "校准模型版本不存在或不可用")
    try:
        return version_file(version_directory(asset_id, version), relative)
    except (OSError, ValueError) as error:
        raise ApiProblem(404, "TILES_FILE_NOT_FOUND", "校准模型文件不存在或不可用") from error

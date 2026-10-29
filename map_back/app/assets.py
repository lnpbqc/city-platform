"""Local, directory-scoped assets; external layer URLs are never fetched."""
import json
import hashlib
from datetime import timezone
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from threading import Lock
from urllib.parse import unquote, urlsplit
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .database import FILES_DIR, STORAGE_DIR
from .models import Asset, AssetVersion, Layer, Run, RunAssetReference, Scene, SceneAssetReference
from .errors import ApiProblem
from .asset_metadata import build_metadata
from .builtin_assets import builtin_asset_files, builtin_asset_for_url

_deletion_lock = Lock()


def lock_catalog(session: Session):
    # Reserve SQLite's writer before checking references or creating new ones.
    if not session.in_transaction():
        session.execute(text("BEGIN IMMEDIATE"))


def valid_identity(identity: str):
    try:
        return str(UUID(identity)) == identity
    except ValueError:
        return False


def reject_link(path: Path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("目录含符号链接或目录联接，禁止访问和删除")
    return info


def directory(root: Path, identity: str):
    if not valid_identity(identity):
        raise ValueError("资产目录标识无效")
    reject_link(STORAGE_DIR)
    reject_link(root)
    target = root / identity
    reject_link(target)
    if target.resolve().parent != root.resolve() or not target.is_dir():
        raise ValueError("资产目录越界或不是目录")
    return target


def inventory(root: Path, identity: str):
    target = directory(root, identity)
    files = []

    def walk(folder: Path):
        for child in folder.iterdir():
            info = reject_link(child)
            if child.resolve().is_relative_to(target.resolve()) is False:
                raise ValueError("资产内部路径越界")
            if stat.S_ISDIR(info.st_mode):
                walk(child)
            elif stat.S_ISREG(info.st_mode):
                files.append({"path": child.relative_to(target).as_posix(), "size": info.st_size})
            else:
                raise ValueError("资产包含非常规文件")

    walk(target)
    return sorted(files, key=lambda item: item["path"])


def detect_entry(identity: str, files: list[dict]):
    paths = {item["path"] for item in files}
    tiles = [path for path in paths if path == "tileset.json" or (path.count("/") == 1 and path.endswith("/tileset.json"))]
    geo = [item["path"] for item in files if item["size"] <= 10 * 1024 * 1024 and Path(item["path"]).suffix.lower() in (".json", ".geojson")]
    for kind, candidates in (("3dtiles", tiles), ("geojson", geo)):
        valid = []
        for relative in candidates:
            try:
                data = json.loads((FILES_DIR / identity / relative).read_text(encoding="utf-8-sig"))
                if isinstance(data, dict) and ((kind == "geojson" and data.get("type") == "FeatureCollection") or (kind == "3dtiles" and isinstance(data.get("asset"), dict) and isinstance(data.get("root"), dict))):
                    valid.append(relative)
            except (OSError, ValueError):
                continue
        if len(valid) == 1:
            return kind, f"/data-files/{identity}/{valid[0]}"
    return "unknown", None


def local_parts(url: str):
    parsed = urlsplit(url)
    if parsed.scheme:
        try:
            known_host = parsed.hostname in ("localhost", "127.0.0.1", "::1") and parsed.port in (8000, 5173, 4173)
        except ValueError:
            raise HTTPException(422, "本地文件地址端口无效")
        if not known_host or not parsed.path.startswith("/data-files/"):
            return None
    if not parsed.path.startswith("/data-files/"):
        return None
    if parsed.query or parsed.fragment:
        raise HTTPException(422, "本地文件地址不能包含查询参数或片段")
    decoded = unquote(parsed.path.removeprefix("/data-files/"))
    parts = decoded.split("/")
    if len(parts) < 2 or not valid_identity(parts[0]) or any(part in ("", ".", "..") or "\\" in part or ":" in part for part in parts):
        raise HTTPException(422, "本地文件地址包含不安全路径")
    return parts[0], PurePosixPath(*parts[1:]).as_posix()


def asset_for_url(session: Session, url: str, kind: str):
    builtin_id = builtin_asset_for_url(url)
    if builtin_id:
        asset = session.get(Asset, builtin_id)
        if asset is None:
            raise HTTPException(422, "默认样例尚未纳入资产目录")
        if asset.type != kind:
            raise HTTPException(422, "图层类型与默认资产类型不一致")
        if asset.status != "active":
            raise HTTPException(409, "默认资产不可用，不能新增引用")
        try:
            _, files, entry = builtin_asset_files(asset.id, asset.entry_url)
        except (OSError, ValueError) as error:
            raise HTTPException(422, f"默认资产不可用：{error}") from error
        if entry not in {item["path"] for item in files}:
            raise HTTPException(422, "默认资产入口缺失")
        return asset.id
    parts = local_parts(url)
    if parts is None:
        key = external_registration_key(url)
        asset = session.scalar(select(Asset).where(Asset.registration_key == key))
        if asset is None:
            return None
        if asset.type != kind or asset.status != "active":
            raise ApiProblem(422, "CONTENT_INVALID", "外部资产类型不符或不可用")
        return asset.id
    identity, relative = parts
    asset = session.get(Asset, identity)
    if asset is None:
        raise HTTPException(422, "本地文件未纳入资产台账，请先扫描存储目录")
    if asset.status != "active":
        raise HTTPException(409, "文件资产不可用或正在删除，不能新增引用")
    try:
        files = inventory(FILES_DIR, identity)
    except (OSError, ValueError) as error:
        raise HTTPException(422, f"本地文件资产不可用：{error}") from error
    if relative not in {item["path"] for item in files}:
        raise HTTPException(422, "本地文件不存在")
    if asset.type != kind:
        raise HTTPException(422, "图层类型与文件资产类型不一致")
    if (kind == "geojson" and Path(relative).suffix.lower() not in (".json", ".geojson")) or (kind == "3dtiles" and Path(relative).name != "tileset.json"):
        raise HTTPException(422, "请使用有效的图层入口文件")
    return asset.id


def references(session: Session, identity: str):
    linked = [{"id": layer.id, "name": layer.name} for layer in session.scalars(select(Layer).where(Layer.asset_id == identity).order_by(Layer.created_at))]
    linked.extend({"type": "scene", "id": scene.id, "name": scene.document["name"], "version": scene.version,
                   "asset_version": reference.asset_version} for scene, reference in session.execute(
                       select(Scene, SceneAssetReference).join(SceneAssetReference, Scene.id == SceneAssetReference.scene_id)
                       .where(SceneAssetReference.asset_id == identity).order_by(Scene.created_at, Scene.id, SceneAssetReference.asset_version)))
    linked.extend({"type": "run", "id": run.id, "name": run.input_snapshot["scene"]["name"], "version": run.scene_version,
                   "asset_version": reference.asset_version} for run, reference in session.execute(
                       select(Run, RunAssetReference).join(RunAssetReference, Run.id == RunAssetReference.run_id)
                       .where(RunAssetReference.asset_id == identity).order_by(Run.submitted_at, Run.id, RunAssetReference.asset_version)))
    return linked


def published_files(asset: Asset, entry_url: str | None = None):
    entry_url = asset.entry_url if entry_url is None else entry_url
    if asset.source_kind == "default":
        return builtin_asset_files(asset.id, entry_url)
    files = inventory(FILES_DIR, asset.id)
    parts = local_parts(entry_url) if entry_url else None
    if parts and parts[0] != asset.id:
        raise ValueError("资产入口与目录标识不一致")
    return directory(FILES_DIR, asset.id), files, parts[1] if parts else ""


def ensure_initial_version(session: Session, asset: Asset):
    version = session.get(AssetVersion, (asset.id, asset.current_version))
    if version is None:
        version = AssetVersion(asset_id=asset.id, version=asset.current_version, entry_url=asset.entry_url,
                               byte_size=asset.byte_size, file_count=asset.file_count,
                               created_at=asset.uploaded_at or asset.discovered_at)
        session.add(version)
    if asset.source_kind != "external" and asset.status == "active":
        root, files, entry = published_files(asset, version.entry_url)
        metadata = build_metadata(root, files, entry, asset.type)
        if version.sha256 is None:
            version.sha256 = metadata["sha256"]
            version.file_manifest = metadata["files"]
            version.bounds = metadata["bounds"]
        elif version.sha256 != metadata["sha256"]:
            asset.status, asset.error = "unsafe", "资产内容已变化，与发布版本校验和不一致"
    return version


def external_registration_key(url: str):
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password
            or any(character.isspace() for character in url)):
            raise ValueError("unsupported URL")
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = parts.port
        if port and (parts.scheme, port) not in (("http", 80), ("https", 443)):
            host += f":{port}"
        return parts._replace(scheme=parts.scheme.lower(), netloc=host, path=parts.path or "/", fragment="").geturl()
    except ValueError as error:
        raise ApiProblem(422, "CONTENT_INVALID", "请使用无嵌入凭据的 HTTP(S) 地址或已受管入口，不支持原始磁盘路径") from error


def version_record(asset: Asset, version: AssetVersion):
    created_at = version.created_at
    external = asset.source_kind == "external"
    return {"asset_id": asset.id, "version": version.version,
            "name": asset.name or asset.original_name or asset.id, "type": asset.type,
            "source_kind": asset.source_kind, "protected": asset.protected, "source": asset.source,
            "coordinate_description": asset.coordinate_description, "entry_url": version.entry_url,
            "byte_size": None if external else sum(item["size"] for item in version.file_manifest) if version.file_manifest is not None else version.byte_size,
            "file_count": None if external else len(version.file_manifest) if version.file_manifest is not None else version.file_count,
            "sha256": version.sha256, "file_checksums": version.file_manifest or [], "bounds": version.bounds,
            "status": {"active": "ready", "missing": "missing"}.get(asset.status, "unsafe"),
            "created_at": created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at.astimezone(timezone.utc)}


def bind_asset_version(session: Session, layer: Layer, asset_id: str | None, replace=False):
    if asset_id is None:
        layer.asset_version = None
    elif replace or layer.asset_id != asset_id or layer.asset_version is None:
        layer.asset_version = session.get(Asset, asset_id).current_version
    layer.asset_id = asset_id


def asset_record(session: Session, asset: Asset, detail=False, inspect_files=True):
    fields = ("id", "original_name", "type", "entry_url", "byte_size", "file_count", "uploaded_at", "discovered_at", "status", "error", "current_version", "source_kind", "protected", "name", "source", "coordinate_description")
    result = {key: getattr(asset, key) for key in fields}
    version = session.get(AssetVersion, (asset.id, asset.current_version))
    result.update(sha256=version.sha256 if version else None, bounds=version.bounds if version else None)
    files = []
    if asset.source_kind == "external":
        result.update(byte_size=None, file_count=None)
    elif inspect_files and asset.status not in ("deleting", "delete_error"):
        try:
            _, files, entry = published_files(asset)
            result.update(byte_size=sum(item["size"] for item in files), file_count=len(files))
            if entry and entry not in {item["path"] for item in files}:
                result.update(status="missing", error="图层入口文件缺失")
        except FileNotFoundError:
            result.update(status="missing", error="发布目录或文件缺失", byte_size=0, file_count=0)
        except (OSError, ValueError) as error:
            result.update(status="unsafe", error=str(error))
    result["references"] = references(session, asset.id)
    result["reference_count"] = len(result["references"])
    if detail:
        result["files"] = files
        result["file_checksums"] = version.file_manifest or [] if version else []
    return result


def reconcile(session: Session):
    lock_catalog(session)
    reject_link(STORAGE_DIR)
    reject_link(FILES_DIR)
    discovered = 0
    for child in FILES_DIR.iterdir():
        if not valid_identity(child.name):
            continue
        asset = session.get(Asset, child.name)
        if asset and (asset.status in ("deleting", "delete_error") or asset.source_kind in ("external", "default")):
            continue
        discovered_asset = asset is None
        if asset is None:
            asset = Asset(id=child.name, original_name=None, type="unknown", entry_url=None, uploaded_at=None, byte_size=0, file_count=0, status="active", error="")
            session.add(asset)
            discovered += 1
        try:
            files = inventory(FILES_DIR, child.name)
            if discovered_asset:
                asset.type, asset.entry_url = detect_entry(child.name, files)
            asset.byte_size = sum(item["size"] for item in files)
            asset.file_count = len(files)
            asset.status, asset.error = "active", ""
            parts = local_parts(asset.entry_url) if asset.entry_url else None
            if parts and parts[1] not in {item["path"] for item in files}:
                asset.status, asset.error = "missing", "图层入口文件缺失"
        except (OSError, ValueError) as error:
            asset.status, asset.error = "unsafe", str(error)[:1000]
    session.flush()
    for asset in session.scalars(select(Asset)):
        try:
            if asset.source_kind == "default":
                _, files, entry = published_files(asset)
                asset.byte_size, asset.file_count = sum(item["size"] for item in files), len(files)
                asset.status, asset.error = ("active", "") if entry in {item["path"] for item in files} else ("missing", "图层入口文件缺失")
            elif asset.source_kind != "external" and not (FILES_DIR / asset.id).exists() and asset.status not in ("deleting", "delete_error"):
                asset.status, asset.error = "missing", "发布目录缺失"
                asset.byte_size, asset.file_count = 0, 0
            ensure_initial_version(session, asset)
        except FileNotFoundError:
            asset.status, asset.error = "missing", "发布目录或文件缺失"
            asset.byte_size, asset.file_count = 0, 0
        except (OSError, ValueError) as error:
            asset.status, asset.error = "unsafe", str(error)[:1000]
    for layer in session.scalars(select(Layer)):
        try:
            bind_asset_version(session, layer, asset_for_url(session, layer.url, layer.type))
        except HTTPException:
            # Keep known references even when files are unavailable or unsafe.
            try:
                parts = local_parts(layer.url)
            except HTTPException:
                parts = None
            try:
                builtin_id = builtin_asset_for_url(layer.url)
            except HTTPException:
                builtin_id = None
            if builtin_id and session.get(Asset, builtin_id):
                bind_asset_version(session, layer, builtin_id)
            elif parts and session.get(Asset, parts[0]):
                bind_asset_version(session, layer, parts[0])
    session.commit()
    return {"assets": [asset_record(session, item) for item in session.scalars(select(Asset).order_by(Asset.discovered_at.desc()))], "discovered": discovered}


def delete_asset(session: Session, identity: str):
    # File operations are outside the database transaction; serialize local
    # deletions so a duplicate request cannot race a retry or the final commit.
    with _deletion_lock:
        _delete_asset(session, identity)


def prepare_download(session: Session, identity: str):
    # Snapshot into non-public temporary storage before releasing the deletion lock.
    with _deletion_lock:
        asset = session.get(Asset, identity)
        if asset is None:
            raise HTTPException(404, "文件资产不存在")
        if asset.status != "active":
            raise HTTPException(409, "文件资产不可用或正在删除，不能下载")
        if asset.source_kind == "external":
            raise ApiProblem(409, "EXTERNAL_ASSET", "外部资产请打开数据源，后端不代理下载")
        temporary = None
        try:
            root, files, entry = published_files(asset)
            if not entry or entry not in {item["path"] for item in files}:
                raise HTTPException(409, "文件资产入口缺失，不能下载")
            version = session.get(AssetVersion, (asset.id, asset.current_version))
            if version and version.sha256:
                if build_metadata(root, files, entry, asset.type)["sha256"] != version.sha256:
                    raise ApiProblem(409, "ASSET_CONTENT_CHANGED", "资产内容与发布版本校验和不一致，请检查文件")
            staging = STORAGE_DIR / "tmp"
            staging.mkdir(exist_ok=True)
            reject_link(staging)
            temporary = Path(tempfile.mkdtemp(prefix="download-", dir=staging))
            if asset.type == "geojson":
                target = temporary / "data.geojson"
                shutil.copyfile(root / entry, target)
                filename = Path((asset.original_name or "data.geojson").replace("\\", "/")).name
                media_type = "application/geo+json"
            elif asset.type == "3dtiles":
                target = temporary / "dataset.zip"
                with ZipFile(target, "w", compression=ZIP_DEFLATED, compresslevel=1) as archive:
                    for item in files:
                        archive.write(root / item["path"], item["path"])
                filename = Path((asset.original_name or "dataset.zip").replace("\\", "/")).stem + ".zip"
                media_type = "application/zip"
            else:
                raise HTTPException(409, "未识别的数据类型，不能下载")
            if version and version.file_manifest:
                expected = {item["path"]: item["sha256"] for item in version.file_manifest}
                if asset.type == "geojson":
                    with target.open("rb") as stream:
                        matches = hashlib.file_digest(stream, "sha256").hexdigest() == expected[entry]
                else:
                    with ZipFile(target) as snapshot:
                        matches = True
                        for path, digest in expected.items():
                            with snapshot.open(path) as stream:
                                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                                    matches = False
                                    break
                if not matches:
                    raise ApiProblem(409, "ASSET_CONTENT_CHANGED", "下载快照与发布版本校验和不一致")
            return target, filename, media_type, temporary
        except Exception as error:
            if temporary:
                shutil.rmtree(temporary)
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(409, "文件资产不可用，下载未完成，请检查文件状态后重试") from error


def _delete_asset(session: Session, identity: str):
    lock_catalog(session)
    asset = session.get(Asset, identity)
    if asset is None:
        raise HTTPException(404, "文件资产不存在")
    if asset.protected or asset.source_kind == "default":
        raise ApiProblem(403, "ASSET_PROTECTED", "默认数据仅可移除图层登记，禁止删除实体文件")
    linked = references(session, identity)
    if linked:
        counts = {kind: len({reference["id"] for reference in linked if reference.get("type", "layer") == kind})
                  for kind in ("layer", "scene", "run")}
        message = f"资产仍被 {counts['layer']} 个图层、{counts['scene']} 个场景、{counts['run']} 个历史运行引用"
        raise HTTPException(409, {"message": message, "references": linked, "reference_count": len(linked)})
    if asset.source_kind == "external":
        session.delete(asset)
        session.commit()
        return
    asset.status, asset.error = "deleting", ""
    session.commit()
    # From this commit onwards create/update reject references to this asset.
    staging = STORAGE_DIR / "deleting"
    try:
        reject_link(STORAGE_DIR)
        staging.mkdir(exist_ok=True)
        reject_link(staging)
        published = FILES_DIR / identity
        staged = staging / identity
        if published.exists() or published.is_symlink() or published.is_junction():
            inventory(FILES_DIR, identity)
            if staged.exists() or staged.is_symlink() or staged.is_junction():
                raise ValueError("删除暂存目录已存在，需检查文件状态")
            shutil.move(str(directory(FILES_DIR, identity)), str(staged))
        if staged.exists() or staged.is_symlink() or staged.is_junction():
            inventory(staging, identity)
            shutil.rmtree(directory(staging, identity))
        session.delete(asset)
        session.commit()
    except Exception as error:
        session.rollback()
        asset = session.get(Asset, identity)
        asset.status, asset.error = "delete_error", str(error)[:1000]
        session.commit()
        raise HTTPException(500, "文件删除未完成，已保留错误状态，可重试") from error

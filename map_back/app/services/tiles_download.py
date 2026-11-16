"""Stream a coherent 3D Tiles ZIP using bounded chunks and ZIP64 support."""
import hashlib
import os
import shutil
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from app.errors import ApiProblem
from app.models import Asset, AssetVersion
from app.services.assets import calibrated_parts, directory, local_parts, lock_catalog, tiles_zip_filename, version_directory, version_file
from app.database import FILES_DIR
from app.services.builtin_assets import builtin_asset_location
from app.services.tiles_calibration import temporary_tile_directory

CHUNK_SIZE = 1024 * 1024


def download_version(session, asset_id, version=None, *, revision=None, snapshot=True):
    lock_catalog(session)
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise ApiProblem(404, "ASSET_NOT_FOUND", "文件资产不存在")
    if asset.status != "active":
        raise ApiProblem(409, "TILES_SOURCE_UNAVAILABLE", "模型资产不可用或正在删除")
    if asset.type != "3dtiles" or asset.source_kind == "external":
        raise ApiProblem(422, "TILES_EXPORT_UNSUPPORTED", "只能下载本地 3D Tiles 模型的版本压缩包")
    version = version or asset.current_version
    record = session.get(AssetVersion, (asset_id, version))
    if record is None:
        raise ApiProblem(404, "ASSET_VERSION_NOT_FOUND", "资产版本不存在")
    if revision is not None and revision != record.revision:
        raise ApiProblem(409, "ASSET_VERSION_CONFLICT", "模型已更新，请重新加载后下载")
    if not record.entry_url or not record.file_manifest:
        raise ApiProblem(409, "TILES_SOURCE_UNAVAILABLE", "模型版本缺少可下载的文件清单")
    files = record.file_manifest
    temporary = None
    try:
        if calibrated_parts(record.entry_url):
            identity, revision, entry = calibrated_parts(record.entry_url)
            if (identity, revision) != (asset_id, version):
                raise ValueError("模型版本入口与记录不一致")
            root = version_directory(asset_id, version)
        elif asset.source_kind == "default":
            root, entry = builtin_asset_location(asset_id, record.entry_url)
        else:
            identity, entry = local_parts(record.entry_url)
            if identity != asset_id:
                raise ValueError("模型版本入口与记录不一致")
            root = directory(FILES_DIR, asset_id)
        if not any(item["path"] == entry for item in files):
            raise ValueError("入口不在资产清单中")
        filename = quote(tiles_zip_filename(asset))
        temporary = temporary_tile_directory("tiles-download-")
        for item in files:
            source = version_file(root, item["path"])
            target = temporary / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if asset.source_kind == "default":
                shutil.copyfile(source, target)
            else:
                os.link(source, target, follow_symlinks=False)
    except (OSError, ValueError, TypeError) as error:
        if temporary:
            shutil.rmtree(temporary, ignore_errors=True)
        raise ApiProblem(409, "ASSET_CONTENT_CHANGED", "无法读取已发布的模型文件") from error
    finally:
        session.rollback()
    try:
        for item in files:
            path = item["path"]
            with version_file(temporary, path).open("rb") as source:
                if (os.fstat(source.fileno()).st_size != item["size"] or
                        hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]):
                    raise ValueError("模型文件与清单不一致")
    except (OSError, ValueError) as error:
        shutil.rmtree(temporary, ignore_errors=True)
        raise ApiProblem(409, "ASSET_CONTENT_CHANGED", f"模型文件无法通过校验：{path}") from error
    if not snapshot:
        shutil.rmtree(temporary, ignore_errors=True)
        temporary = None
    return temporary, files, {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
                              "Cache-Control": "no-store"}


class _ZipOutput:
    def __init__(self):
        self.pending = bytearray()

    def write(self, data):
        self.pending.extend(data)
        return len(data)

    def flush(self):
        pass

    def drain(self):
        data = bytes(self.pending)
        self.pending.clear()
        return data


def stream_zip(root, files):
    output = _ZipOutput()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for item in files:
            path = item["path"]
            digest = hashlib.sha256()
            length = 0
            with (version_file(root, path).open("rb") as source,
                  archive.open(path, "w", force_zip64=item["size"] >= 2**31 - 1) as target):
                while chunk := source.read(CHUNK_SIZE):
                    digest.update(chunk)
                    length += len(chunk)
                    target.write(chunk)
                    if len(output.pending) >= CHUNK_SIZE:
                        yield output.drain()
            if length != item["size"] or digest.hexdigest() != item["sha256"]:
                raise ValueError(f"模型文件与已发布版本不一致：{path}")
            if len(output.pending) >= CHUNK_SIZE:
                yield output.drain()
    if output.pending:
        yield output.drain()

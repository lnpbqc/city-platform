import hashlib
import io
from uuid import NAMESPACE_URL, uuid5
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import builtin_assets
from app.assets import asset_for_url, asset_record, reconcile
from app.database import FILES_DIR, SessionLocal
from app.models import Asset, AssetVersion, Layer


def register():
    with SessionLocal() as session:
        builtin_assets.ensure_builtin_assets(session)
        session.commit()


def test_builtin_registration_is_idempotent_with_stable_ids_urls_and_no_copy(client):
    before = set(FILES_DIR.iterdir())
    register()
    register()
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Asset)) == 10
        assert session.scalar(select(func.count()).select_from(AssetVersion)) == 10
        for campus in builtin_assets.CAMPUS_KEYS:
            for layer in builtin_assets.BUILTIN_LAYERS:
                identity = str(uuid5(NAMESPACE_URL, f"city:sample:{campus}:{layer['id']}"))
                assert builtin_assets.builtin_asset_id(campus, layer["id"]) == identity
                asset = session.get(Asset, identity)
                assert asset.entry_url == f"/samples/{campus}/{layer['filename']}"
                assert asset.source_kind == "default" and asset.protected is True
                assert session.get(AssetVersion, (identity, "1.0.0")).sha256
    assert set(FILES_DIR.iterdir()) == before


@pytest.mark.parametrize("layer_id,expected_paths", [
    ("demo-points", {"water-points.geojson"}),
    ("demo-buildings", {"tileset.json", "buildings.glb"}),
])
def test_default_detail_has_only_its_own_dataset_and_real_metadata(client, layer_id, expected_paths):
    register()
    identity = builtin_assets.builtin_asset_id("university-town", layer_id)
    detail = client.get(f"/api/assets/{identity}")
    assert detail.status_code == 200, detail.text
    result = detail.json()
    assert result["status"] == "active"
    assert {item["path"] for item in result["files"]} == expected_paths
    assert {item["path"] for item in result["file_checksums"]} == expected_paths
    assert result["file_count"] == len(expected_paths)
    assert result["bounds"] is not None


def test_sample_entry_whitelist_binds_asset_and_rejects_unlisted_paths(client):
    register()
    identity = builtin_assets.builtin_asset_id("huangpu", "demo-roads")
    with SessionLocal() as session:
        assert asset_for_url(session, "/samples/huangpu/roads.geojson", "geojson") == identity
        for url in ("/samples/huangpu/../water-points.geojson", "/samples/huangpu/%2e%2e/roads.geojson",
                    "/samples/huangpu/roads.geojson?x=1", "/samples/huangpu/buildings/buildings.glb", "/samples/unknown/roads.geojson"):
            with pytest.raises(HTTPException) as error:
                asset_for_url(session, url, "geojson")
            assert error.value.status_code == 422
        with pytest.raises(HTTPException):
            asset_for_url(session, "/samples/huangpu/roads.geojson", "3dtiles")


@pytest.mark.parametrize("prefix", ["http://localhost:8000", "https://127.0.0.1:5173", "http://[::1]:4173"])
def test_builtin_local_http_aliases_use_same_protected_asset(client, prefix):
    register()
    entry = "/samples/huangpu/roads.geojson"
    identity = builtin_assets.builtin_asset_id("huangpu", "demo-roads")
    assert builtin_assets.builtin_asset_for_url(prefix + entry) == identity
    with SessionLocal() as session:
        assert asset_for_url(session, prefix + entry, "geojson") == identity
    for suffix in ("?x=1", "#section"):
        with pytest.raises(HTTPException) as error:
            builtin_assets.builtin_asset_for_url(prefix + entry + suffix)
        assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        builtin_assets.builtin_asset_for_url(prefix + "/samples/huangpu/unlisted.geojson")
    assert error.value.status_code == 422


@pytest.mark.parametrize("prefix", ["https://example.invalid", "http://localhost:80", "https://localhost:443", "http://localhost:9999"])
def test_remote_or_other_port_sample_urls_stay_external(client, prefix):
    register()
    url = prefix + "/samples/huangpu/roads.geojson?token=allowed-for-external"
    assert builtin_assets.builtin_asset_for_url(url) is None
    with SessionLocal() as session:
        assert asset_for_url(session, url, "geojson") is None


def test_reconcile_retains_legacy_invalid_local_sample_url_without_failing_startup(client):
    register()
    url = "http://localhost:8000/samples/old-unlisted.geojson?legacy=1"
    with SessionLocal() as session:
        session.add(Layer(id="legacy-sample", name="历史地址", category="专题", type="geojson", url=url))
        session.commit()
        reconcile(session)
        assert session.get(Layer, "legacy-sample").url == url
        assert session.get(Layer, "legacy-sample").asset_id is None


def test_reconcile_keeps_defaults_active_and_pinned_without_storage_directories(client):
    register()
    identity = builtin_assets.builtin_asset_id("university-town", "demo-points")
    with SessionLocal() as session:
        asset = session.get(Asset, identity)
        digest = session.get(AssetVersion, (identity, "1.0.0")).sha256
        session.add(Layer(id="old-default", name="默认登记", category="专题", type="geojson", url=asset.entry_url,
                          asset_id=identity, asset_version="1.0.0"))
        session.commit()
        reconcile(session)
        assert session.get(Asset, identity).status == "active"
        assert session.get(Layer, "old-default").asset_version == "1.0.0"
        assert session.get(AssetVersion, (identity, "1.0.0")).sha256 == digest
        assert asset_record(session, asset)["byte_size"] > 0
    assert not (FILES_DIR / identity).exists()


@pytest.mark.parametrize("layer_id", ["demo-points", "demo-buildings"])
def test_default_download_and_delete_preserve_source_bytes(client, layer_id):
    register()
    identity = builtin_assets.builtin_asset_id("university-town", layer_id)
    with SessionLocal() as session:
        asset = session.get(Asset, identity)
        root, files, entry = builtin_assets.builtin_asset_files(identity, asset.entry_url)
        before = {item["path"]: hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() for item in files}
    response = client.get(f"/api/assets/{identity}/download")
    assert response.status_code == 200, response.text
    if layer_id == "demo-points":
        assert hashlib.sha256(response.content).hexdigest() == before[entry]
    else:
        with ZipFile(io.BytesIO(response.content)) as archive:
            assert set(archive.namelist()) == set(before)
            assert {path: hashlib.sha256(archive.read(path)).hexdigest() for path in archive.namelist()} == before
    assert client.delete(f"/api/assets/{identity}").status_code == 403
    assert {item["path"]: hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() for item in files} == before


def test_default_path_helper_rejects_id_or_entry_mismatch(client):
    identity = builtin_assets.builtin_asset_id("university-town", "demo-points")
    with pytest.raises(ValueError):
        builtin_assets.builtin_asset_files(identity, "/samples/huangpu/water-points.geojson")
    with pytest.raises(ValueError):
        builtin_assets.builtin_asset_files("00000000-0000-0000-0000-000000000000", "/samples/university-town/water-points.geojson")


def test_reconcile_detects_default_changes_without_replacing_fingerprint(client, monkeypatch):
    register()
    identity = builtin_assets.builtin_asset_id("university-town", "demo-points")
    from app import assets
    original = assets.build_metadata

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        result["sha256"] = "0" * 64
        return result

    with SessionLocal() as session:
        digest = session.get(AssetVersion, (identity, "1.0.0")).sha256
        monkeypatch.setattr(assets, "build_metadata", changed)
        reconcile(session)
        assert session.get(Asset, identity).status == "unsafe"
        assert session.get(AssetVersion, (identity, "1.0.0")).sha256 == digest

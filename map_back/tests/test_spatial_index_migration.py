import os
from pathlib import Path
import subprocess
import sys


def test_rtree_backfill_update_cascade_and_reupgrade(tmp_path):
    storage = tmp_path / 'rtree-migration'
    environment = {**os.environ, 'MAP_STORAGE_DIR': str(storage),
                   'MAP_DATABASE_URL': 'sqlite:///' + (storage / 'catalog.db').as_posix(), 'PYTHONIOENCODING': 'utf-8'}
    script = r'''
import json
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.database import SessionLocal, engine
from app.main import app

config = Config('alembic.ini')
command.upgrade(config, 'head')
try:
    client = TestClient(app)
    uploaded = client.post('/api/layers/upload', data={'name':'old','type':'geojson','category':'POI'},
        files={'file':('old.geojson',json.dumps({'type':'FeatureCollection','features':[{'type':'Feature',
        'geometry':{'type':'Point','coordinates':[121.5,25]},'properties':{}}]}))})
    assert uploaded.status_code == 201, uploaded.text
    layer = uploaded.json()
    # Seed with current APIs, then exercise the genuine pre-RTree schema.
    command.downgrade(config, '0012_workspace_bookmarks')
    with SessionLocal() as session:
        original = session.execute(text('SELECT id,geometry,properties FROM spatial_objects')).all()
    command.upgrade(config, 'head')
    for iteration in range(2):
        with SessionLocal() as session:
            assert session.execute(text('SELECT id,geometry,properties FROM spatial_objects')).all() == original
            assert session.execute(text('SELECT count(*) FROM object_rtree')).scalar_one() == 1
            assert session.execute(text('PRAGMA foreign_key_check')).all() == []
        if iteration == 0:
            command.downgrade(config, '0012_workspace_bookmarks')
            command.upgrade(config, 'head')
    with SessionLocal() as session:
        session.execute(text('UPDATE spatial_objects SET west=122,east=122 WHERE asset_id=:asset'), {'asset':layer['asset_id']})
        assert session.execute(text('SELECT west FROM object_rtree')).scalar_one() == 122
        session.execute(text('DELETE FROM layers WHERE id=:id'), {'id':layer['id']})
        session.execute(text('DELETE FROM assets WHERE id=:id'), {'id':layer['asset_id']})
        session.commit()
        assert session.execute(text('SELECT count(*) FROM object_rtree')).scalar_one() == 0
        assert session.execute(text('SELECT count(*) FROM object_spatial_keys')).scalar_one() == 0
finally:
    engine.dispose()
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1], env=environment,
                            capture_output=True, timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    assert result.returncode == 0, result.stdout.decode('utf-8', errors='replace') + result.stderr.decode('utf-8', errors='replace')

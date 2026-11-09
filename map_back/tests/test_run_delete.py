import pytest
from app.database import SessionLocal
from app.models import Run, Scene
from app.run_artifacts import RUNS_DIR
from test_runs import setup_run, queued_client, paused_queue


def terminal(client):
    item = client.post('/api/runs', json=setup_run(client)).json()
    client.post(f"/api/runs/{item['run_id']}/cancel")
    return item['run_id']


@pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled'])
def test_delete_terminal_removes_files_and_record(queued_client, status):
    if status == 'cancelled':
        identity = terminal(queued_client)
    else:
        item = queued_client.post('/api/runs', json=setup_run(queued_client)).json()
        identity = item['run_id']
        from app.run_store import claim_next, finish_run
        assert claim_next() == identity
        finish_run(identity, status, result={} if status == 'succeeded' else None,
                   error={'code': 'TEST_FAILURE', 'message': 'failed'} if status == 'failed' else None)
    assert (RUNS_DIR / identity).exists()
    response = queued_client.delete('/api/runs/' + identity)
    assert response.status_code == 204, response.text
    assert queued_client.get('/api/runs/' + identity).status_code == 404
    assert not (RUNS_DIR / identity).exists()


def test_delete_active_and_referenced_runs_are_protected(queued_client):
    item = queued_client.post('/api/runs', json=setup_run(queued_client)).json()
    assert queued_client.delete('/api/runs/' + item['run_id']).json()['code'] == 'RUN_NOT_TERMINAL'
    queued_client.post(f"/api/runs/{item['run_id']}/cancel")
    with SessionLocal() as session:
        scene = session.get(Scene, item['scene_id'])
        scene.document = {**scene.document, 'run_id': item['run_id']}
        session.commit()
    response = queued_client.delete('/api/runs/' + item['run_id'])
    assert response.status_code == 409 and response.json()['code'] == 'RUN_IN_USE'
    assert response.json()['detail']['references'][0]['type'] == 'scene'


def test_delete_bookmarked_run_is_protected(queued_client):
    from app.models import Bookmark
    from uuid import uuid4
    identity = terminal(queued_client)
    with SessionLocal() as session:
        session.add(Bookmark(id=str(uuid4()), name='固定结果', kind='scene', state={'run_id': identity}))
        session.commit()
    response = queued_client.delete('/api/runs/' + identity)
    assert response.status_code == 409 and response.json()['detail']['references'][0]['type'] == 'bookmark'


def test_delete_commit_failure_restores_files(queued_client, monkeypatch):
    identity = terminal(queued_client)
    from sqlalchemy.orm import Session
    original = Session.commit
    def fail(session):
        if any(isinstance(item, Run) for item in session.deleted):
            raise RuntimeError('commit failed')
        return original(session)
    monkeypatch.setattr(Session, 'commit', fail)
    import pytest
    with pytest.raises(RuntimeError, match='commit failed'):
        queued_client.delete('/api/runs/' + identity)
    assert (RUNS_DIR / identity / 'input.json').exists()
    assert queued_client.get('/api/runs/' + identity).status_code == 200


def test_stale_result_reader_cannot_republish_deleted_run(queued_client):
    from app.run_artifacts import publish
    from app.errors import ApiProblem
    identity = terminal(queued_client)
    with SessionLocal() as reader:
        stale = reader.get(Run, identity)
        assert queued_client.delete('/api/runs/' + identity).status_code == 204
        with pytest.raises(ApiProblem) as error:
            publish(stale, result_only=True)
        assert error.value.code == 'RUN_NOT_FOUND'
    assert not (RUNS_DIR / identity).exists()


def test_run_snapshot_keeps_removed_layer_and_scene_readable(queued_client):
    from test_timeseries import custom_snapshot, TIMES
    from test_scenes import draft, layer_state
    layer = custom_snapshot(queued_client)
    scene = queued_client.post('/api/scenes', json={**draft(), 'layers': [{**layer_state(layer), 'name': '旧地点', 'category': 'POI'}]}).json()
    body = {**setup_run(queued_client), 'scene_id': scene['id']}
    item = queued_client.post('/api/runs', json=body).json()
    queued_client.post(f"/api/runs/{item['run_id']}/cancel")
    assert queued_client.delete('/api/layers/' + layer['id']).status_code == 204
    assert queued_client.delete('/api/scenes/' + scene['id'], headers={'If-Match': '"1"'}).status_code == 204
    query = {'asset_id': layer['asset_id'], 'version': layer['asset_version']}
    response = queued_client.get('/api/layers/' + layer['id'] + '/times', params=query)
    assert response.status_code == 200 and response.json() == [TIMES[0]], response.text
    assert queued_client.get('/api/objects', params={**query, 'layer_id': layer['id']}).status_code == 200
    from app.object_queries import referenced_layer_category, ObjectFilters
    with SessionLocal() as session:
        assert referenced_layer_category(session, ObjectFilters(**query, layer_id=layer['id'])) == 'POI'


def test_delete_file_cleanup_failure_restores_run(queued_client, monkeypatch):
    identity = terminal(queued_client)
    from app import run_artifacts
    original = run_artifacts.shutil.rmtree
    def fail(path, *args, **kwargs):
        if str(path).endswith('snapshot'):
            raise PermissionError('file busy')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(run_artifacts.shutil, 'rmtree', fail)
    with pytest.raises(PermissionError, match='file busy'):
        queued_client.delete('/api/runs/' + identity)
    assert queued_client.get('/api/runs/' + identity).status_code == 200
    assert (RUNS_DIR / identity / 'input.json').exists()

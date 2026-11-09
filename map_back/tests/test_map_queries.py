import json

from sqlalchemy import text
from app.database import SessionLocal


def upload(client, features, category="POI"):
    response = client.post('/api/layers/upload', data={'name': '查询数据', 'category': category, 'type': 'geojson'},
                           files={'file': ('points.geojson', json.dumps({'type': 'FeatureCollection', 'features': features}))})
    assert response.status_code == 201, response.text
    return response.json()


def point(name, x=121.5, y=25, **properties):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [x, y]}, 'properties': {'name': name, **properties}}


def reference(layer):
    return {'layer_id': layer['id'], 'asset_id': layer['asset_id'], 'version': layer['asset_version']}


def test_viewport_selects_weight_before_budget_and_preserves_original_identity(client):
    layer = upload(client, [point('low', weight=1), point('high', importance=10, custom='kept')])
    body = {**reference(layer), 'bbox': [121.4, 24.9, 121.6, 25.1], 'width': 640, 'height': 480, 'meters_per_pixel': .5}
    response = client.post('/api/map/viewport', json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result['features']) == 2
    feature = result['features'][0]
    assert feature['properties']['name'] == 'high'
    assert feature['properties']['custom'] == 'kept'
    assert feature['__object']['feature_index'] == 1
    objects = client.get('/api/objects', params={'layer_id': layer['id']}).json()['items']
    assert feature['id'] == next(item['object_id'] for item in objects if item['name'] == 'high')
    assert client.post('/api/map/viewport', json=body).json() == result


def test_nearby_includes_hidden_points_and_sorts_distance(client):
    layer = upload(client, [point('far', x=121.505, weight=100), point('near', x=121.5001), point('outside', x=121.52)])
    result = client.post('/api/map/nearby', json={'layers': [reference(layer)], 'longitude': 121.5, 'latitude': 25})
    assert result.status_code == 200, result.text
    items = result.json()['items']
    assert [item['name'] for item in items] == ['near', 'far']
    assert 0 < items[0]['distance_m'] < items[1]['distance_m'] < 1000
    assert items[0]['layer_id'] == layer['id']


def test_light_poi_detail_and_attribute_edit_preserve_original_height(client):
    feature = point('elevated')
    feature['geometry']['coordinates'].append(123.45)
    layer = upload(client, [feature])
    result = client.post('/api/map/nearby', json={'layers': [reference(layer)], 'longitude': 121.5, 'latitude': 25}).json()
    identity = result['items'][0]['object_id']
    item = client.get('/api/map/objects/' + identity).json()
    assert item['geometry']['coordinates'] == [121.5, 25, 123.45]
    assert result['items'][0]['geometry']['coordinates'] == [121.5, 25, 123.45]
    changed = client.post(f"/api/layers/{layer['id']}/poi-features", json={
        'asset_id': layer['asset_id'], 'version': layer['asset_version'], 'operation': 'update', 'object_id': identity,
        'feature': {'type': 'Feature', 'geometry': item['geometry'], 'properties': {'name': 'renamed'}}})
    assert changed.status_code == 200, changed.text
    saved = client.get(changed.json()['url']).json()['features'][0]
    assert saved['geometry']['coordinates'] == [121.5, 25, 123.45]


def test_rtree_tracks_import_and_cascade_delete(client):
    layer = upload(client, [point('one')])
    with SessionLocal() as session:
        identity = session.execute(text('SELECT id FROM spatial_objects WHERE asset_id=:asset'), {'asset': layer['asset_id']}).scalar_one()
        assert session.execute(text('SELECT count(*) FROM object_spatial_keys k JOIN object_rtree r ON r.id=k.id WHERE k.object_id=:id'), {'id': identity}).scalar_one() == 1
        session.execute(text('DELETE FROM spatial_objects WHERE id=:id'), {'id': identity})
        session.commit()
        assert session.execute(text('SELECT count(*) FROM object_spatial_keys WHERE object_id=:id'), {'id': identity}).scalar_one() == 0


def test_light_detail_and_custom_category(client):
    layer = upload(client, [point('custom')], category='我的专题')
    item = client.get('/api/objects', params={'layer_id': layer['id']}).json()['items'][0]
    response = client.get('/api/map/objects/' + item['object_id'])
    assert response.status_code == 200, response.text
    assert response.json()['geometry']['type'] == 'Point'
    assert next(row for row in client.get('/api/layers/catalog').json() if row['id'] == layer['id'])['category'] == '我的专题'


def test_viewport_validates_bounds_and_versions(client):
    layer = upload(client, [point('one')])
    body = {**reference(layer), 'bbox': [181, 0, 182, 1], 'width': 640, 'height': 480, 'meters_per_pixel': .5}
    assert client.post('/api/map/viewport', json=body).status_code == 422
    body['bbox'] = [121, 24, 122, 26]
    body['version'] = 'missing'
    assert client.post('/api/map/viewport', json=body).status_code in (404, 422)


def test_viewport_budgets_and_weight_precedence(client, monkeypatch):
    from app import map_queries
    # Highest importance is late in the source and a different display cell.
    layer = upload(client, [point('low', x=121.41, weight=100), point('late-high', x=121.59, importance=101, weight=-100)])
    body = {**reference(layer), 'bbox': [121.4, 24.9, 121.6, 25.1], 'width': 640, 'height': 480, 'meters_per_pixel': .5}
    monkeypatch.setattr(map_queries, 'MAX_FEATURES', 1)
    result = client.post('/api/map/viewport', json=body).json()
    assert result['truncated'] is True
    assert [feature['properties']['name'] for feature in result['features']] == ['late-high']
    monkeypatch.setattr(map_queries, 'MAX_BYTES', 128)
    result = client.post('/api/map/viewport', json=body).json()
    assert result['truncated'] is True and result['features'] == []


def test_line_display_is_simplified_without_changing_original(client, monkeypatch):
    from app import map_queries
    coordinates = [[121.4 + index * 0.001, 25] for index in range(201)]
    feature = {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': coordinates}, 'properties': {}}
    layer = upload(client, [feature], category='道路')
    body = {**reference(layer), 'bbox': [121.45, 24.9, 121.55, 25.1], 'width': 640, 'height': 480, 'meters_per_pixel': .5}
    result = client.post('/api/map/viewport', json=body).json()
    assert len(result['features']) == 1
    rendered = result['features'][0]
    assert len(rendered['geometry']['coordinates']) == 2
    assert rendered['geometry']['coordinates'][0][0] >= 121.45
    identity = rendered['id']
    assert client.get('/api/objects/' + identity).json()['geometry']['coordinates'] == coordinates
    assert client.get('/api/map/objects/' + identity).json()['geometry'] is None
    monkeypatch.setattr(map_queries, 'MAX_VERTICES', 1)
    result = client.post('/api/map/viewport', json=body).json()
    assert result['truncated'] is True and result['features'] == []


def test_nearby_cross_layer_limit_antimeridian_and_validation(client):
    first = upload(client, [point(str(i), x=179.999 + i * 0.00001, y=0) for i in range(21)])
    second = upload(client, [point('cross-date-line', x=-179.9999, y=0)])
    body = {'layers': [reference(first), reference(second)], 'longitude': -180, 'latitude': 0}
    result = client.post('/api/map/nearby', json=body)
    assert result.status_code == 200, result.text
    items = result.json()['items']
    assert len(items) == 20 and items[0]['name'] == 'cross-date-line'
    assert items == sorted(items, key=lambda item: (item['distance_m'], item['object_id'], item['layer_id']))
    body['latitude'] = 91
    assert client.post('/api/map/nearby', json=body).status_code == 422


def test_nearby_reports_external_unavailable_and_rejects_other_categories(client):
    external = client.post('/api/assets/register', json={'name': 'external', 'type': 'geojson', 'location': 'https://example.invalid/poi.json'}).json()
    layer = client.post('/api/layers', json={'name': 'external', 'type': 'geojson', 'category': 'POI', 'url': external['entry_url']}).json()
    body = {'layers': [reference(layer)], 'longitude': 121.5, 'latitude': 25}
    result = client.post('/api/map/nearby', json=body)
    assert result.status_code == 200, result.text
    assert result.json() == {'items': [], 'unavailable_layers': [layer['id']]}
    other = upload(client, [point('not-poi')], category='水体')
    body['layers'] = [reference(other)]
    assert client.post('/api/map/nearby', json=body).status_code == 422


def test_viewport_counts_real_intersections_before_feature_budget(client, monkeypatch):
    from app import map_queries
    # A polygon's envelope intersects the viewport while its hole covers it entirely.
    hole = {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [
        [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]]]}, 'properties': {}}
    layer = upload(client, [hole, point('inside', x=2, y=2)], category='专题')
    monkeypatch.setattr(map_queries, 'MAX_FEATURES', 1)
    result = client.post('/api/map/viewport', json={**reference(layer), 'bbox': [1.5, 1.5, 2.5, 2.5], 'width': 640, 'height': 480, 'meters_per_pixel': .5}).json()
    assert [feature['properties']['name'] for feature in result['features']] == ['inside']
    assert result['truncated'] is False

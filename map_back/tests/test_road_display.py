from test_map_queries import upload, reference


def road(name, coordinates, highway='primary', **props):
    return {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': coordinates},
            'properties': {'name': name, 'highway': highway, **props}}


def view(client, layer, mpp, **values):
    return client.post('/api/map/viewport', json={**reference(layer), 'bbox': [0, 0, .1, .1],
                       'width': 800, 'height': 600, 'meters_per_pixel': mpp, **values})


def test_roads_filter_before_budget_and_preserve_originals(client, monkeypatch):
    from app import map_queries
    layer = upload(client, [road('小路', [[.01,.01],[.02,.01]], 'footway'), road('主路', [[.01,.02],[.02,.02]])], '道路')
    monkeypatch.setattr(map_queries, 'MAX_FEATURES', 1)
    result = view(client, layer, 30)
    assert result.status_code == 200, result.text
    data = result.json()
    assert [f['properties']['name'] for f in data['features']] == ['主路']
    assert data['features'][0]['__display']['road_class'] == 'primary'
    assert client.get('/api/objects', params={'layer_id':layer['id']}).json()['total'] == 2


def test_road_bbox_false_positive_does_not_consume_budget(client, monkeypatch):
    from app import map_queries
    layer = upload(client,[road('外侧主路',[[0,0],[0,.1],[.1,.1]]),
                           road('视野次路',[[.04,.05],[.06,.05]],'secondary')],'道路')
    monkeypatch.setattr(map_queries,'MAX_FEATURES',1)
    result = view(client,layer,.5,bbox=[.04,.04,.06,.06]).json()
    assert [f['properties']['name'] for f in result['features']] == ['视野次路']


def test_feature_budget_selects_whole_road_before_side_streets(client, monkeypatch):
    from app import map_queries
    layer = upload(client, [road('主路', [[.01,.01],[.02,.01]]),
                            road('主路', [[.02,.01],[.03,.01]]),
                            road('次路', [[.01,.02],[.02,.02]], 'secondary')], '道路')
    monkeypatch.setattr(map_queries, 'MAX_FEATURES', 1)
    data = view(client, layer, 10).json()
    assert data['truncated']
    assert len(data['features']) == 1
    assert len(data['features'][0]['__object']['source_object_ids']) == 2


def test_named_roads_merge_but_junction_bridge_and_parallel_do_not(client):
    layer = upload(client, [road('路', [[.01,.01],[.02,.01]]), road('路', [[.02,.01],[.03,.01]])], '道路')
    result = view(client, layer, .5).json()
    assert len(result['features']) == 1
    feature = result['features'][0]
    assert len(feature['__object']['source_object_ids']) == 2
    sources = client.get('/api/objects', params={'layer_id':layer['id']}).json()['items']
    picked = client.post('/api/map/road-pick', json={**reference(layer), 'object_ids':feature['__object']['source_object_ids'],
                         'longitude':.029,'latitude':.01})
    assert picked.status_code == 200, picked.text
    assert picked.json()['feature_index'] == 1
    assert len(picked.json()['geometry']['coordinates']) == 2
    assert len(sources) == 2
    for extra in [road('支路', [[.02,.01],[.02,.02]]), road('路', [[.02,.01],[.03,.01]], bridge='yes')]:
        original = [road('路', [[.01,.01],[.02,.01]]), road('路', [[.02,.01],[.03,.01]])]
        layer = upload(client, original + [extra], '道路')
        assert all(len(f['__object']['source_object_ids']) == 1 for f in view(client,layer,.5).json()['features'])


def test_roads_scale_boundaries_and_hidden_geometries(client):
    values = [('primary',30),('secondary',20),('residential',5),('service',1)]
    layer = upload(client, [road(kind, [[.01,.01+i*.01],[.02,.01+i*.01]], kind) for i,(kind,_) in enumerate(values)] +
        [road('施工', [[.01,.06],[.02,.06]],'construction'),
         {'type':'Feature','geometry':{'type':'Polygon','coordinates':[[[.01,.07],[.02,.07],[.02,.08],[.01,.07]]]},'properties':{'highway':'pedestrian'}}], '道路')
    for count, (_,mpp) in enumerate(values,1):
        result = view(client,layer,mpp,road_max_level=4)
        assert result.status_code == 200, result.text
        assert len(result.json()['features']) == count
    assert view(client,layer,-1).status_code == 422


def test_road_pick_rejects_foreign_sources(client):
    first = upload(client,[road('一',[[.01,.01],[.02,.01]])],'道路')
    other = upload(client,[road('二',[[.01,.01],[.02,.01]])],'道路')
    identity = client.get('/api/objects',params={'layer_id':other['id']}).json()['items'][0]['object_id']
    result = client.post('/api/map/road-pick',json={**reference(first),'object_ids':[identity],'longitude':.01,'latitude':.01})
    assert result.status_code == 422


def test_shared_route_number_does_not_erase_different_street_names(client):
    layer = upload(client, [road('东街', [[.01,.01],[.02,.01]], ref='G1'),
                            road('西街', [[.02,.01],[.03,.01]], ref='G1')], '道路')
    result = view(client,layer,.5).json()['features']
    assert len(result) == 2
    assert {feature['properties']['name'] for feature in result} == {'东街','西街'}


def test_parallel_ring_and_elevated_roads_keep_geometry(client):
    ring = road('环路', [[.01,.01],[.02,.01],[.02,.02],[.01,.01]])
    parallel = road('环路', [[.01,.011],[.02,.011]])
    elevated = road('高架', [[.04,.01,10],[.05,.01,10]])
    ground = road('高架', [[.05,.01,0],[.06,.01,0]])
    layer = upload(client,[ring,parallel,elevated,ground],'道路')
    features = view(client,layer,.5).json()['features']
    assert len(features) == 4
    assert all(len(f['__object']['source_object_ids']) == 1 for f in features)
    assert any(f['geometry']['coordinates'][0] == f['geometry']['coordinates'][-1] for f in features)


def test_poi_scale_semantics_do_not_remove_nearby_candidates(client):
    from test_map_queries import point
    layer = upload(client,[point('学校',amenity='school'), point('某某大学',amenity='university'),
                           point('测试饭店',amenity='restaurant')])
    far = client.post('/api/map/viewport',json={**reference(layer),'bbox':[121.4,24.9,121.6,25.1],
                      'width':800,'height':600,'meters_per_pixel':10}).json()
    assert [f['properties']['name'] for f in far['features']] == ['某某大学']
    assert far['features'][0]['__display']['poi_category'] == '教育'
    nearby = client.post('/api/map/nearby',json={'layers':[reference(layer)],'longitude':121.5,'latitude':25}).json()
    assert len(nearby['items']) == 3


def test_road_level_ceiling_defaults_and_scale_intersection(client):
    kinds = ['primary', 'secondary', 'residential', 'service']
    layer = upload(client, [road(kind, [[.01,.01+i*.01],[.02,.01+i*.01]], kind) for i, kind in enumerate(kinds)], '道路')
    assert [f['properties']['name'] for f in view(client, layer, .5).json()['features']] == kinds[:2]
    for level in range(1, 5):
        features = view(client, layer, .5, road_max_level=level).json()['features']
        assert [f['properties']['name'] for f in features] == kinds[:level]
    assert len(view(client, layer, 30, road_max_level=4).json()['features']) == 1
    for invalid in (0, 5, 1.5, True, '2', None):
        assert view(client, layer, .5, road_max_level=invalid).status_code == 422


def test_road_level_catalog_persistence_and_validation(client):
    layer = upload(client, [road('路', [[.01,.01],[.02,.01]])], '道路')
    for identity in (layer['id'], 'basemap'):
        url = f'/api/layers/catalog/{identity}/map-state'
        for invalid in (0, 5, 1.5, True, None):
            assert client.patch(url, json={'road_max_level': invalid}).status_code == 422
        updated = client.patch(url, json={'road_max_level': 4})
        assert updated.status_code == 200, updated.text
        assert updated.json()['road_max_level'] == 4
        assert next(row for row in client.get('/api/layers/catalog').json() if row['id'] == identity)['road_max_level'] == 4


def test_road_level_scene_legacy_default_and_explicit_snapshot(client):
    from test_scenes import draft, layer_state
    layer = upload(client, [road('road', [[.01,.01],[.02,.01]])], '道路')
    state = layer_state(layer)
    state.pop('road_max_level')
    for level in (None, 4):
        body = draft()
        body['layers'] = [dict(state, **({'road_max_level': level} if level else {}))]
        response = client.post('/api/scenes', json=body)
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved['layers'][0]['road_max_level'] == (level or 2)
        assert client.get('/api/scenes/' + saved['id']).json()['layers'] == saved['layers']


def test_tile_road_group_pick_matches_original_and_checks_version(client, monkeypatch, tmp_path):
    import json
    from datetime import datetime
    from app import rendering
    from app.database import SessionLocal
    from app.render_models import RenderJob
    layer = upload(client, [road('road', [[.01,.01],[.02,.01]]), road('road', [[.02,.01],[.03,.01]])], '道路')
    sources = client.get('/api/objects', params={'layer_id': layer['id']}).json()['items']
    identities = [item['object_id'] for item in sources]
    key = 'a' * 64
    monkeypatch.setattr(rendering, 'RENDER_DIR', tmp_path)
    (tmp_path / key).mkdir()
    (tmp_path / key / 'road_sources.jsonl').write_text(json.dumps({'group_id': 'group-one', 'source_object_ids': identities}) + '\n', encoding='utf8')
    with SessionLocal() as session:
        session.add(RenderJob(key=key, asset_id=layer['asset_id'], version=layer['asset_version'], profile='roads', recipe='test', status='succeeded', created_at=datetime.now(), updated_at=datetime.now()))
        session.commit()
    body = {**reference(layer), 'display_group_id': 'group-one', 'render_key': key, 'longitude': .029, 'latitude': .01}
    response = client.post('/api/map/road-pick', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['feature_index'] == 1
    assert client.post('/api/map/road-pick', json={**body, 'render_key': 'b' * 64}).status_code == 422
    assert client.post('/api/map/road-pick', json={**body, 'display_group_id': 'missing'}).status_code == 422
    assert client.post('/api/map/road-pick', json={**body, 'object_ids': identities}).status_code == 422
    selected = {**reference(layer), 'render_key': key, 'object_ids': [identities[1], 'unknown']}
    groups = client.post('/api/map/road-groups', json=selected)
    assert groups.status_code == 200, groups.text
    assert groups.json() == {'groups': [{'group_id': 'group-one', 'object_ids': [identities[1]]}]}
    assert client.post('/api/map/road-groups', json={**selected, 'render_key': 'b' * 64}).status_code == 422
    other = upload(client, [road('other', [[.01,.01],[.02,.01]])], '道路')
    assert client.post('/api/map/road-groups', json={**selected, **reference(other)}).status_code == 422


def test_road_bends_survive_wide_camera_bbox_at_fixed_scale(client):
    import math
    curves = [
        [[.01 + i * .001, .02 + .001 * math.sin(i * math.pi / 50)] for i in range(51)],
        [[.01 + i * .001, .04 + .001 * math.sin(i * math.pi / 25)] for i in range(51)],
        [[.08 + .005 * math.cos(i * math.pi / 25), .08 + .005 * math.sin(i * math.pi / 25)] for i in range(50)],
        [[.02 + i * .0001, .07 + .0001 * (i / 10) ** 2] for i in range(21)],
    ]
    curves[2].append(curves[2][0])
    features = [road(str(i), coords, 'primary_link' if i == 3 else 'primary') for i, coords in enumerate(curves)]
    for category in ('道路', '专题'):
        layer = upload(client, features, category)
        for bbox in ([0, 0, .1, .1], [-10, -10, 10, 10]):
            response = view(client, layer, 2, bbox=bbox)
            assert response.status_code == 200, response.text
            rendered = {f['properties']['name']: f for f in response.json()['features']}
            for i, coords in enumerate(curves):
                assert rendered[str(i)]['geometry']['coordinates'] == coords


def test_generic_roads_join_before_feature_and_vertex_budgets(client, monkeypatch):
    from app import map_queries
    secondary = road('次路', [[.01,.02],[.02,.02]], 'secondary', importance=100)
    first = road('主路', [[.01,.01],[.015,.011],[.02,.01]])
    second = road('主路', [[.02,.01],[.025,.009],[.03,.01]])
    second['properties'].pop('highway')
    second['properties']['fclass'] = 'primary'
    nonroad = road('survey', [[.01,.03],[.015,.03],[.02,.03]], importance=1000)
    nonroad['properties'].pop('highway')
    layer = upload(client, [nonroad, secondary, first, second], '专题')
    monkeypatch.setattr(map_queries, 'MAX_FEATURES', 1)
    result = view(client, layer, 2).json()
    assert result['truncated']
    assert len(result['features']) == 1
    main = result['features'][0]
    assert main['properties']['name'] == '主路'
    assert len(main['__object']['source_object_ids']) == 2
    expected = first['geometry']['coordinates'] + second['geometry']['coordinates'][1:]
    assert main['geometry']['coordinates'] in (expected, expected[::-1])
    monkeypatch.setattr(map_queries, 'MAX_VERTICES', 4)
    result = view(client, layer, 2).json()
    assert result['truncated']
    assert [f['properties']['name'] for f in result['features']] == ['次路']
    monkeypatch.setattr(map_queries, 'MAX_BYTES', 128)
    assert view(client, layer, 2).json() == {'type': 'FeatureCollection', 'features': [], 'truncated': True}


def test_generic_hidden_branch_still_stops_chain_joining(client):
    layer = upload(client, [road('主路', [[.01,.01],[.02,.01]]),
                            road('主路', [[.02,.01],[.03,.01]]),
                            road('支路', [[.02,.01],[.02,.02]], 'service')], '专题')
    features = view(client, layer, 2).json()['features']
    assert len(features) == 2
    assert all(len(f['__object']['source_object_ids']) == 1 for f in features)


def test_road_multilines_keep_turns_and_only_remove_exact_duplicates(client):
    first = [[.01,.01,0],[.01,.01,0],[.02,.011,0],[.02,.011,10],[.03,.01,10]]
    second = [[.04,.01,0],[.045,.011,0],[.05,.01,0]]
    feature = road('multi', [])
    feature['geometry'] = {'type': 'MultiLineString', 'coordinates': [first, second]}
    layer = upload(client, [feature], category='道路')
    rendered = view(client, layer, 2, bbox=[-10,-10,10,10]).json()['features'][0]
    assert rendered['geometry']['coordinates'] == [first[:1] + first[2:], second]

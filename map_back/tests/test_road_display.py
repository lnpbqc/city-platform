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
        result = view(client,layer,mpp)
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

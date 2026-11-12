import json
import math
import tempfile
import unittest
from pathlib import Path

from tile_service.service import Settings, Store, check_source_url, prepare


def feature(identity, coords, **props):
    return {'type': 'Feature', '__object': {'object_id': identity, 'feature_index': int(identity)},
            'properties': {'highway': 'primary', 'name': '连接路', **props},
            'geometry': {'type': 'LineString', 'coordinates': coords}}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_idempotent_queue_and_restart_retries_only_once(self):
        store = Store(self.root)
        payload = {'key': 'a', 'asset_id': 'x', 'version': '1.0.0', 'recipe': 'geojson-v1',
                   'profile': 'roads', 'source_url': 'http://localhost:8000/internal/render-source/x/1.0.0'}
        first = store.submit(payload)
        self.assertEqual(first['id'], store.submit(payload)['id'])
        store.claim()
        store.recover()
        self.assertEqual(store.get(first['id'])['status'], 'queued')
        store.claim()
        store.recover()
        self.assertEqual(store.get(first['id'])['status'], 'failed')

    def test_explicit_retry_can_regenerate_an_acknowledged_artifact(self):
        store = Store(self.root)
        payload = {'key': 'retry', 'asset_id': 'x', 'version': '1.0.0', 'recipe': 'geojson-v1',
                   'profile': 'roads', 'source_url': 'http://localhost:8000/internal/render-source/x/1.0.0'}
        first = store.submit(payload)
        store.update(first['id'], status='succeeded', acknowledged=1)
        self.assertEqual(store.submit(payload)['id'], first['id'])
        replacement = store.submit({**payload, 'retry': True})
        self.assertNotEqual(first['id'], replacement['id'])
        self.assertEqual(replacement['status'], 'queued')

    def test_ssrf_origin_and_exact_source_path(self):
        config = Settings(root=self.root, token='secret', backend_origin='http://localhost:8000')
        check_source_url(config, 'http://localhost:8000/internal/render-source/x/1.0.0', 'x', '1.0.0')
        for url in ('http://evil.test/internal/render-source/x/1.0.0',
                    'http://localhost:8000/admin', 'http://user@localhost:8000/internal/render-source/x/1.0.0'):
            with self.assertRaises(ValueError):
                check_source_url(config, url, 'x', '1.0.0')

    def write_source(self, items):
        source = self.root / 'source.json'
        source.write_text(json.dumps({'type': 'FeatureCollection', 'features': items}), encoding='utf8')
        return source

    def test_compatible_road_chains_keep_sources_and_bridge_boundaries(self):
        source = self.write_source([
            feature('0', [[113, 23], [113.001, 23]]),
            feature('1', [[113.001, 23], [113.002, 23]]),
            feature('2', [[113.002, 23], [113.003, 23]], bridge='yes'),
        ])
        stats = prepare(source, self.root, 'roads', lambda: None)
        displayed = [json.loads(line) for line in (self.root / 'render.jsonl').read_text(encoding='utf8').splitlines()]
        groups = [json.loads(line) for line in (self.root / 'road_sources.jsonl').read_text(encoding='utf8').splitlines()]
        self.assertEqual(stats['feature_count'], 3)
        self.assertEqual(len(displayed), 2)
        self.assertIn(['0', '1'], [item['source_object_ids'] for item in groups])
        self.assertEqual(displayed[0]['properties']['road_rank'], 0)
        self.assertEqual(len(displayed[0]['geometry']['coordinates']), 3)

    def test_precision_collapse_fails_with_source_identity(self):
        source = self.write_source([feature('7', [[113, 23], [113.00000001, 23]])])
        with self.assertRaisesRegex(ValueError, '7'):
            prepare(source, self.root, 'roads', lambda: None)

    def test_junctions_do_not_merge_and_closed_loop_preserves_vertices(self):
        items = []
        # Thirty-four isolated three-way junctions, each with the same road name.
        for junction in range(34):
            x = 112 + junction * 0.01
            for branch, endpoint in enumerate(((x - .001, 23), (x + .001, 23), (x, 23.001))):
                items.append(feature(str(junction * 3 + branch), [[x, 23], list(endpoint)]))
        items.append(feature('102', [[113, 24], [113.001, 24], [113.001, 24.001], [113, 24]]))
        source = self.write_source(items)
        stats = prepare(source, self.root, 'roads', lambda: None)
        self.assertEqual(stats['display_feature_count'], 103)
        displayed = [json.loads(line) for line in (self.root / 'render.jsonl').read_text(encoding='utf8').splitlines()]
        loop = next(item for item in displayed if item['properties']['object_id'] == '102')
        self.assertEqual(loop['geometry']['coordinates'][0], loop['geometry']['coordinates'][-1])
        first = (self.root / 'road_sources.jsonl').read_bytes()
        (self.root / 'spool.sqlite3').unlink()
        prepare(source, self.root, 'roads', lambda: None)
        self.assertEqual(first, (self.root / 'road_sources.jsonl').read_bytes())

    def test_reserved_identity_and_poi_style_override_untrusted_properties(self):
        item = feature('4', [[113, 23], [113.001, 23]], object_id='wrong', huge='drop')
        source = self.write_source([item])
        prepare(source, self.root, 'generic', lambda: None)
        props = json.loads((self.root / 'render.jsonl').read_text(encoding='utf8'))['properties']
        self.assertEqual(props['object_id'], '4')
        self.assertEqual(props['feature_index'], 4)
        self.assertNotIn('huge', props)

    def test_high_latitude_road_scale_never_omits_an_eligible_grade(self):
        items = [feature(str(index), [[113 + index * .01, 85.05], [113.001 + index * .01, 85.05]], highway=kind)
                 for index, kind in enumerate(('primary', 'secondary', 'residential', 'footway'))]
        prepare(self.write_source(items), self.root, 'roads', lambda: None)
        output = [json.loads(line) for line in (self.root / 'render.jsonl').read_text(encoding='utf8').splitlines()]
        for item in output:
            rank = item['properties']['road_rank']
            if rank:
                threshold = (20, 5, 1)[rank - 1]
                zoom = math.floor(math.log2(156543.033928 * math.cos(math.radians(85.05)) / threshold))
                self.assertLessEqual(item['tippecanoe']['minzoom'], zoom)

    def test_generic_explicit_roads_keep_conservative_minzoom(self):
        items = [feature(str(index), [[113 + index * .01, 23], [113.001 + index * .01, 23]], highway=kind)
                 for index, kind in enumerate(('primary', 'secondary', 'residential', 'footway'))]
        stats = prepare(self.write_source(items), self.root, 'generic', lambda: None)
        output = [json.loads(line) for line in (self.root / 'render.jsonl').read_text(encoding='utf8').splitlines()]
        self.assertTrue(stats['contains_roads'])
        self.assertEqual([item['tippecanoe']['minzoom'] for item in output], [0, 9, 11, 13])

    def test_generic_road_chains_merge_curves_but_leave_ordinary_lines_untouched(self):
        items = [feature('0', [[113, 23], [113.0005, 23.0003], [113.001, 23]]),
                 feature('1', [[113.001, 23], [113.0015, 22.9997], [113.002, 23]]),
                 feature('2', [[114, 23], [114.001, 23]]),
                 feature('3', [[114.001, 23], [114.002, 23]])]
        for item in items[2:]:
            item['properties'] = {'name': 'ordinary line'}
        stats = prepare(self.write_source(items), self.root, 'generic', lambda: None)
        output = [json.loads(line) for line in (self.root / 'render.jsonl').read_text(encoding='utf8').splitlines()]
        groups = [json.loads(line) for line in (self.root / 'road_sources.jsonl').read_text(encoding='utf8').splitlines()]
        self.assertEqual(stats['display_feature_count'], 3)
        self.assertEqual([group['source_object_ids'] for group in groups], [['0', '1']])
        merged = next(item for item in output if item['properties']['object_id'] == '0')
        self.assertEqual(len(merged['geometry']['coordinates']), 5)
        self.assertEqual(merged['properties']['display_group_id'], groups[0]['group_id'])
        ordinary = [item for item in output if item['properties']['object_id'] in ('2', '3')]
        self.assertEqual(len(ordinary), 2)
        self.assertTrue(all('display_group_id' not in item['properties'] for item in ordinary))

    def test_generic_nonroad_branch_stops_road_chain_joining(self):
        items = [feature('0', [[113, 23], [113.001, 23]]),
                 feature('1', [[113.001, 23], [113.002, 23]]),
                 feature('2', [[113.001, 23], [113.001, 23.001]])]
        items[2]['properties'] = {'name': 'ordinary branch'}
        stats = prepare(self.write_source(items), self.root, 'generic', lambda: None)
        groups = [json.loads(line) for line in (self.root / 'road_sources.jsonl').read_text(encoding='utf8').splitlines()]
        self.assertEqual(stats['display_feature_count'], 3)
        self.assertEqual([group['source_object_ids'] for group in groups], [['0'], ['1']])

    def test_generic_point_and_nonroad_polygon_do_not_enable_road_recipe(self):
        point = feature('0', [113, 23])
        point['geometry']['type'] = 'Point'
        polygon = feature('1', [[[113, 23], [113.001, 23], [113.001, 23.001], [113, 23]]])
        polygon['geometry']['type'] = 'Polygon'
        polygon['properties'] = {'fclass': 'park'}
        stats = prepare(self.write_source([point, polygon]), self.root, 'generic', lambda: None)
        self.assertFalse(stats['contains_roads'])

    def test_poi_scale_whitelist_and_first_finite_explicit_weight(self):
        item = feature('0', [[113, 23], [113.001, 23]], amenity='hospital', name='中心医院', importance='3.5', weight=8)
        prepare(self.write_source([item]), self.root, 'poi', lambda: None)
        output = json.loads((self.root / 'render.jsonl').read_text(encoding='utf8'))
        self.assertEqual(output['properties']['weight'], 3.5)
        self.assertEqual(output['properties']['max_scale'], 20)
        self.assertTrue(output['properties']['background_eligible'])
        self.assertEqual(output['tippecanoe']['minzoom'], 9)


if __name__ == '__main__':
    unittest.main()

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import generate_campus_buildings as generator
from generate_campus_buildings import building_height, campus_rings, contains, relation_geometry


class CampusBuildingsTests(unittest.TestCase):
    def test_real_campus_generation_includes_multipolygon_teaching_buildings(self):
        campus = json.loads((generator.PROJECT / 'src/data/campuses.json').read_text(encoding='utf8'))[0]
        with tempfile.TemporaryDirectory() as root:
            with patch.object(generator, 'PROJECT', Path(root)):
                generator.generate(campus)
            data = json.loads((Path(root) / 'public/samples/university-town/campus-buildings.geojson').read_text(encoding='utf8'))
        names = {feature['properties']['名称'] for feature in data['features']}
        for name in ['理科教学北楼', '理科教学南楼', '计算机实验楼', '文清楼']:
            self.assertIn(name, names)
        source = json.loads((generator.RESEARCH / 'university-town-osm-20261022.json').read_text(encoding='utf8'))
        ids = {feature['id'] for feature in data['features']}
        for relation in source['elements']:
            if f'osm-relation-{relation["id"]}' not in ids or relation['type'] != 'relation':
                continue
            for member in relation['members']:
                if member['type'] == 'way' and member['role'] == 'outer':
                    self.assertNotIn(f'osm-way-{member["ref"]}', ids)
        self.assertNotIn('osm-relation-18183428', ids)  # building=no
        north = next(f for f in data['features'] if f['properties']['名称'] == '理科教学北楼')
        self.assertEqual(len(north['geometry']['coordinates']), 4)  # outer + three courtyards

    def test_multiple_outer_rings_keep_courtyards_and_winding(self):
        nodes = {1: [0, 0], 2: [4, 0], 3: [4, 4], 4: [0, 4],
                 5: [1, 1], 6: [2, 1], 7: [2, 2], 8: [1, 2],
                 9: [10, 0], 10: [12, 0], 11: [12, 2], 12: [10, 2]}
        ways = {1: {'nodes': [1, 2, 3]}, 2: {'nodes': [1, 4, 3]},
                3: {'nodes': [5, 6, 7, 8, 5]}, 4: {'nodes': [9, 10, 11, 12, 9]}}
        relation = {'id': 1, 'type': 'relation', 'members': [
            {'type': 'way', 'ref': ref, 'role': role}
            for ref, role in [(1, 'outer'), (2, 'outer'), (3, 'inner'), (4, 'outer')]]}
        geometry = relation_geometry(relation, ways, nodes)
        self.assertEqual(geometry['type'], 'MultiPolygon')
        self.assertEqual([len(poly) for poly in geometry['coordinates']], [2, 1])
        for polygon in geometry['coordinates']:
            for index, ring in enumerate(polygon):
                self.assertEqual(ring[0], ring[-1])
                area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))
                self.assertEqual(area > 0, index == 0)

    def test_height_priority_units_and_missing_values(self):
        self.assertEqual(building_height({'height': '17.25', 'building:levels': '4'}), (17.25, 'OSM标注高度（未核验）', False))
        self.assertEqual(building_height({'height': '10 m'}), (10, 'OSM标注高度（未核验）', False))
        self.assertEqual(building_height({'height': '30 ft'})[0], 9.14)
        self.assertEqual(building_height({'height': '-1', 'building:levels': '7'}), (21, '楼层估计：7层 × 3米', True))
        for tags in ({}, {'height': 'nan'}, {'height': 'inf'}, {'height': 'unknown', 'building:levels': '0'}, {'height': '10000'}):
            self.assertEqual(building_height(tags), (9, '缺测估计：统一9米（非实测）', True))

    def test_boundary_segments_join_in_reverse_and_exclude_neighbor(self):
        ways = {1: {'nodes': [1, 2, 3]}, 2: {'nodes': [1, 4, 3]}}
        nodes = {1: [0, 0], 2: [1, 0], 3: [1, 1], 4: [0, 1]}
        boundary = {'type': 'relation', 'members': [{'type': 'way', 'ref': 1, 'role': 'outer'}, {'type': 'way', 'ref': 2, 'role': 'outer'}]}
        rings = campus_rings(boundary, ways, nodes)
        self.assertTrue(contains([0.5, 0.5], rings[0]))
        self.assertFalse(contains([1.5, 0.5], rings[0]))

    def test_incomplete_boundary_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'boundary'):
            campus_rings({'type': 'way', 'nodes': [1, 2]}, {}, {1: [0, 0], 2: [1, 0]})


if __name__ == '__main__':
    unittest.main()

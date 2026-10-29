"""Build campus footprint white models offline from the saved OSM API snapshots."""
import json
import math
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
RESEARCH = PROJECT / 'docs' / 'research'
BOUNDARIES = {'university-town': ('relation', 13970405), 'huangpu': ('way', 1191052293)}


def positive_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def building_height(tags):
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(m|ft|米)?\s*', str(tags.get('height', '')))
    if match:
        height = float(match[1]) * (0.3048 if match[2] == 'ft' else 1)
        if 0 < height <= 1000:
            return round(height, 2), 'OSM标注高度（未核验）', False
    levels = positive_number(tags.get('building:levels'))
    if levels and levels * 3 <= 1000:
        return round(levels * 3, 2), f'楼层估计：{levels:g}层 × 3米', True
    return 9, '缺测估计：统一9米（非实测）', True


def campus_rings(boundary, ways, nodes, role='outer'):
    chains = ([boundary['nodes'][:]] if boundary['type'] == 'way' else
              [ways[m['ref']]['nodes'][:] for m in boundary['members']
               if m['type'] == 'way' and m['role'] == role])
    rings = []
    while chains:
        ring = chains.pop(0)
        while ring[0] != ring[-1]:
            for index, chain in enumerate(chains):
                if chain[0] == ring[-1]:
                    ring.extend(chain[1:])
                elif chain[-1] == ring[-1]:
                    ring.extend(chain[-2::-1])
                else:
                    continue
                chains.pop(index)
                break
            else:
                raise ValueError('Incomplete campus boundary')
        rings.append([nodes[n] for n in ring])
    return rings


def contains(point, ring):
    x, y = point
    inside = False
    for a, b in zip(ring, ring[1:]):
        if (a[1] > y) != (b[1] > y) and x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]:
            inside = not inside
    return inside


def orient(ring, outer=True):
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))
    return ring if (area > 0) == outer else ring[::-1]


def relation_geometry(relation, ways, nodes):
    polygons = [[orient(ring)] for ring in campus_rings(relation, ways, nodes)]
    for hole in campus_rings(relation, ways, nodes, 'inner'):
        for polygon in polygons:
            if contains(hole[0], polygon[0]):
                polygon.append(orient(hole, outer=False))
                break
        else:
            raise ValueError(f'Uncontained courtyard in relation {relation["id"]}')
    if not polygons:
        raise ValueError(f'Missing outer boundary in relation {relation["id"]}')
    return ({'type': 'Polygon', 'coordinates': polygons[0]} if len(polygons) == 1 else
            {'type': 'MultiPolygon', 'coordinates': polygons})


def in_campus(points, rings):
    center = [sum(p[j] for p in points) / len(points) for j in (0, 1)]
    return any(contains(point, ring) for ring in rings for point in [center, *points])


def generate(campus):
    key = campus['key']
    data = json.loads((RESEARCH / f'{key}-osm-20261022.json').read_text(encoding='utf-8'))
    elements = data['elements']
    nodes = {e['id']: [e['lon'], e['lat']] for e in elements if e['type'] == 'node'}
    ways = {e['id']: e for e in elements if e['type'] == 'way'}
    kind, identity = BOUNDARIES[key]
    boundary = next(e for e in elements if e['type'] == kind and e['id'] == identity)
    rings = campus_rings(boundary, ways, nodes)
    buildings = []
    relation_outers = set()
    for relation in sorted((e for e in elements if e['type'] == 'relation'), key=lambda r: r['id']):
        tags = relation.get('tags', {})
        if tags.get('type') != 'multipolygon' or tags.get('building', 'no') == 'no':
            continue
        outers = [m['ref'] for m in relation['members'] if m['type'] == 'way' and m['role'] == 'outer']
        # Bbox API also returns neighboring relations with incomplete members.
        # Only assemble candidates touching this campus; in-campus missing data fails loudly.
        known_points = [nodes[n] for ref in outers if ref in ways for n in ways[ref]['nodes'] if n in nodes]
        if not known_points or not in_campus(known_points, rings):
            continue
        geometry = relation_geometry(relation, ways, nodes)
        buildings.append((relation, geometry))
        relation_outers.update(outers)
    for way in sorted(ways.values(), key=lambda w: w['id']):
        if way['id'] in relation_outers or way.get('tags', {}).get('building', 'no') == 'no':
            continue
        coordinates = [nodes[n] for n in way['nodes']]
        if len(coordinates) < 4 or coordinates[0] != coordinates[-1] or not in_campus(coordinates[:-1], rings):
            continue
        buildings.append((way, {'type': 'Polygon', 'coordinates': [orient(coordinates)]}))
    features = []
    for element, geometry in buildings:
        tags = element['tags']
        height, basis, estimated = building_height(tags)
        osm_url = f'https://www.openstreetmap.org/{element["type"]}/{element["id"]}'
        features.append({
            'type': 'Feature', 'id': f'osm-{element["type"]}-{element["id"]}',
            'geometry': geometry,
            'properties': {
                '名称': tags.get('name', f'未命名建筑 · OSM {element["id"]}'),
                '校区': campus['name'], '数据性质': '公开建筑轮廓生成的简化白模',
                '显示高度_米': height, '高度依据': basis, '高度是否估计': estimated,
                '数据来源': 'OpenStreetMap', '来源链接': osm_url,
                '数据获取日期': '2026-10-22', 'OSM版本': element.get('version'),
                'OSM更新时间': element.get('timestamp'), '建筑类型': tags['building'],
                'OSM高度原值': tags.get('height', '缺测'),
                'OSM楼层原值': tags.get('building:levels', '缺测'),
                'map_extrude_height_m': height,
            },
        })
    output = PROJECT / 'public' / 'samples' / key
    output.mkdir(parents=True, exist_ok=True)
    document = {
        'type': 'FeatureCollection', 'name': f'{campus["name"]}建筑轮廓白模',
        'source': '© OpenStreetMap contributors',
        'license': 'https://opendatacommons.org/licenses/odbl/1-0/',
        'attribution': 'https://www.openstreetmap.org/copyright',
        'description': 'WGS84；OSM公开标注，不保证完整。高度优先height，否则楼层×3米，缺测9米；非测绘模型，无真实立面。',
        'features': features,
    }
    (output / 'campus-buildings.geojson').write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'campus-buildings-LICENSE.txt').write_text(
        '© OpenStreetMap contributors\nODbL 1.0: https://opendatacommons.org/licenses/odbl/1-0/\n'
        'Attribution: https://www.openstreetmap.org/copyright\n'
        f'Campus boundary: https://www.openstreetmap.org/{kind}/{identity}\n'
        'Retrieved 2026-10-22. Derived building footprint database; WGS84.\n'
        'Heights: OSM height where valid; otherwise levels * 3 m; otherwise illustrative 9 m.\n'
        'This is not a surveyed or complete campus model. No facade textures.\n', encoding='utf-8')
    print(f'{key}: {len(features)} building records; {sum(f["properties"]["高度是否估计"] for f in features)} estimated heights')


if __name__ == '__main__':
    for campus in json.loads((PROJECT / 'src' / 'data' / 'campuses.json').read_text(encoding='utf-8')):
        generate(campus)

"""Bounded RTree candidate queries shared by map display and nearby lookup."""
from sqlalchemy import text


def candidates(session, asset_id, version, windows, *, point_only=False, properties=False, endpoints=False):
    """Yield small batches; do not construct an in-memory list of viewport objects."""
    statements, parameters = [], {'asset': asset_id, 'version': version}
    point = " AND json_extract(o.geometry, '$.type')='Point'" if point_only else ''
    weight = 'COALESCE(' + ','.join(f"CASE WHEN json_type(o.properties,'$.{key}') IN ('integer','real') THEN json_extract(o.properties,'$.{key}') END" for key in ('importance', 'weight', 'priority')) + ',0)'
    extra = ',o.properties AS properties' if properties else ''
    if endpoints:
        extra += """,json_extract(o.geometry,'$.type') AS geometry_type,
            CASE json_extract(o.geometry,'$.type')
                WHEN 'LineString' THEN json_array(json_array(
                    json_extract(o.geometry,'$.coordinates[0]'),json_extract(o.geometry,'$.coordinates[#-1]')))
                WHEN 'MultiLineString' THEN (SELECT json_group_array(json_array(
                    json_extract(part.value,'$[0]'),json_extract(part.value,'$[#-1]')))
                    FROM json_each(o.geometry,'$.coordinates') AS part)
            END AS endpoints"""
    for index, (west, south, east, north) in enumerate(windows):
        parameters.update({f'west{index}': west, f'east{index}': east, f'south{index}': south, f'north{index}': north})
        # CROSS JOIN fixes the RTree-first loop order. Otherwise SQLite may start
        # with the asset index and visit every object before checking its envelope.
        statements.append(f'SELECT o.id,o.west,o.south,{weight} AS weight{extra} FROM object_rtree r '
                          'CROSS JOIN object_spatial_keys k ON k.id=r.id CROSS JOIN spatial_objects o ON o.id=k.object_id '
                          'WHERE o.asset_id=:asset AND o.asset_version=:version '
                          f'AND r.west<=:east{index} AND r.east>=:west{index} '
                          f'AND r.south<=:north{index} AND r.north>=:south{index}{point}')
    # UNION prevents duplicate wide envelopes when the viewport crosses ±180°.
    statement = text(' UNION '.join(statements) + ' ORDER BY 1')
    return session.execute(statement, parameters).yield_per(256)

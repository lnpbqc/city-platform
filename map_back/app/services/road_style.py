"""Display-only road classification and topology-safe chain assembly."""
from collections import defaultdict

GROUPS = [('motorway','trunk','primary','motorway_link','trunk_link','primary_link'),
          ('secondary','tertiary','secondary_link','tertiary_link'),
          ('residential','unclassified','living_street'),
          ('service','footway','cycleway','path','steps','pedestrian','track','busway','corridor')]
RANK = {kind: index for index, group in enumerate(GROUPS) for kind in group}


def classification(properties):
    return str(properties.get('highway') or properties.get('fclass') or 'unclassified').lower()


def road_rank(properties, mpp, road_max_level=2):
    rank = RANK.get(classification(properties))
    allowed = 0 if mpp > 20 else 1 if mpp > 5 else 2 if mpp > 1 else 3
    return rank if rank is not None and rank <= min(allowed, road_max_level - 1) else None


def signature(feature):
    props = feature['properties']
    name = props.get('name') or props.get('名称')
    reference = props.get('ref')
    # Anonymous fragments must not be accidentally joined into arbitrary streets.
    identity = str(name or reference).strip() if name or reference else feature['id']
    return tuple(str(value) for value in (identity, name or '', reference or '', classification(props), props.get('bridge','no'),
                 props.get('tunnel','no'),props.get('layer','0'),props.get('oneway','no')))


def road_groups(segments, degrees):
    """Group source IDs using only compatible degree-two endpoints."""
    adjacency = defaultdict(list)
    for identity, (_, key, endpoints) in segments.items():
        for endpoint in endpoints:
            if degrees[endpoint] == 2:
                adjacency[key, endpoint].append(identity)

    visited = set()
    for identity in sorted(segments, key=lambda item: (segments[item][0], item)):
        if identity in visited:
            continue
        pending, group = [identity], []
        while pending:
            item = pending.pop()
            if item in visited:
                continue
            visited.add(item)
            group.append(item)
            _, key, endpoints = segments[item]
            for endpoint in endpoints:
                pending.extend(adjacency.get((key, endpoint), ()))
        yield sorted(group)

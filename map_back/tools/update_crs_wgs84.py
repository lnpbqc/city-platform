import json
from pyproj import Transformer

INPUT = "D:\\BaiduNetdiskDownload\\中国河流矢量图.json"
OUTPUT = "中国河流矢量图_wgs84.geojson"

# 根据实际情况修改：
# 已经是 WGS84 经纬度 -> EPSG:4326
# CGCS2000 经纬度 -> EPSG:4490
# 西安80 经纬度 -> EPSG:4610（精度取决于 towgs84/格网）
# 北京54 经纬度 -> EPSG:4214
SRC_CRS = "EPSG:4326"
DST_CRS = "EPSG:4326"

transformer = Transformer.from_crs(SRC_CRS, DST_CRS, always_xy=True)

def transform_pos(pos):
    x, y = transformer.transform(pos[0], pos[1])
    if len(pos) >= 3:
        return [x, y, pos[2]]
    return [x, y]

def transform_geometry(geom):
    t = geom["type"]
    c = geom["coordinates"]

    if t == "LineString":
        geom["coordinates"] = [transform_pos(p) for p in c]
    elif t == "MultiLineString":
        geom["coordinates"] = [
            [transform_pos(p) for p in line] for line in c
        ]
    elif t == "Point":
        geom["coordinates"] = transform_pos(c)
    elif t == "MultiPoint":
        geom["coordinates"] = [transform_pos(p) for p in c]
    elif t == "Polygon":
        geom["coordinates"] = [
            [transform_pos(p) for p in ring] for ring in c
        ]
    elif t == "MultiPolygon":
        geom["coordinates"] = [
            [[transform_pos(p) for p in ring] for ring in poly]
            for poly in c
        ]
    else:
        raise ValueError(f"未处理的几何类型: {t}")
    return geom

def iter_positions(geom):
    t = geom["type"]
    c = geom["coordinates"]
    if t == "LineString" or t == "MultiPoint":
        yield from c
    elif t == "MultiLineString":
        for line in c:
            yield from line
    elif t == "Point":
        yield c
    elif t == "Polygon":
        for ring in c:
            yield from ring
    elif t == "MultiPolygon":
        for poly in c:
            for ring in poly:
                yield from ring

with open(INPUT, "r", encoding="utf-8") as f:
    data = json.load(f)

# 1. 移除旧式 crs 声明
data.pop("crs", None)
data.pop("bbox", None)  # 顶层 bbox 转换后可能失效，删除或重算

for feature in data.get("features", []):
    feature.pop("crs", None)
    feature.pop("bbox", None)

    if feature.get("geometry"):
        transform_geometry(feature["geometry"])

        # 重算 properties.bbox
        props = feature.get("properties") or {}
        if "bbox" in props:
            xs, ys = [], []
            for p in iter_positions(feature["geometry"]):
                xs.append(p[0])
                ys.append(p[1])
            if xs and ys:
                props["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
            feature["properties"] = props

# 2. 输出标准 GeoJSON，不写 crs 成员
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

print("完成:", OUTPUT)
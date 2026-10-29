"""Rebuild synthetic samples at two Guangzhou University campuses; no real campus assets."""
import json
import math
import shutil
import struct
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

PROJECT = Path(__file__).resolve().parents[1]
BASE = PROJECT / "public" / "samples"
CAMPUSES = json.loads((PROJECT / "src" / "data" / "campuses.json").read_text(encoding="utf-8"))


def generate(campus):
    ROOT = BASE / campus["key"]
    TILES = ROOT / "buildings"
    TILES.mkdir(parents=True, exist_ok=True)
    LON, LAT = campus["longitude"], campus["latitude"]

    def feature(kind, coordinates, **properties):
        return {"type": "Feature", "geometry": {"type": kind, "coordinates": coordinates}, "properties": {"数据性质": "合成演示", "校区": campus["name"], **properties}}


    def write_geo(name, features):
        def scale_coordinates(value):
            if value and isinstance(value[0], (int, float)):
                return [LON + (value[0] - LON) * campus["scale"], LAT + (value[1] - LAT) * campus["scale"]]
            return [scale_coordinates(part) for part in value]
        for item in features:
            item["geometry"]["coordinates"] = scale_coordinates(item["geometry"]["coordinates"])
        (ROOT / name).write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2), encoding="utf-8")


    write_geo("water-points.geojson", [
        feature("Point", [LON - .0015, LAT + .0008], 名称="监测点 A", 积水深度_cm=18, 数据时刻="2026-10-22 09:00", 单位="cm"),
        feature("Point", [LON + .0012, LAT + .0006], 名称="监测点 B", 积水深度_cm=7, 数据时刻="2026-10-22 09:00", 单位="cm"),
        feature("Point", [LON + .0004, LAT - .0012], 名称="监测点 C", 积水深度_cm=12, 数据时刻="2026-10-22 09:00", 单位="cm"),
    ])
    write_geo("roads.geojson", [
        feature("LineString", [[LON - .003, LAT + .0006], [LON + .003, LAT + .0006]], 名称="演示道路 · 东西向", 流量=420, 单位="辆/小时"),
        feature("LineString", [[LON + .0004, LAT - .002], [LON + .0004, LAT + .002]], 名称="演示道路 · 南北向", 流量=260, 单位="辆/小时"),
    ])
    write_geo("areas.geojson", [feature("Polygon", [[[LON - .0024, LAT - .0015], [LON - .0007, LAT - .0015], [LON - .0007, LAT - .0002], [LON - .0024, LAT - .0002], [LON - .0024, LAT - .0015]]], 名称="演示积水范围", 平均深度_cm=12, 来源="人工构造，不代表实测")])

    # Generate flat-shaded cuboids in a local z-up ENU frame; convert to glTF y-up.
    positions, normals = [], []
    for cx, cy, width, depth, height in [(-85, 95, 40, 35, 62), (-20, 90, 32, 42, 100), (55, 90, 40, 38, 74), (110, 20, 35, 35, 48), (-25, -40, 50, 40, 38), (55, -55, 35, 30, 58)]:
        corners = [(cx + x * width / 2, cy + y * depth / 2, z * height) for x, y, z in [(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]
        for quad, normal in [((0,3,2,1),(0,0,-1)),((4,5,6,7),(0,0,1)),((0,1,5,4),(0,-1,0)),((1,2,6,5),(1,0,0)),((2,3,7,6),(0,1,0)),((3,0,4,7),(-1,0,0))]:
            for vertex in [quad[0],quad[1],quad[2],quad[0],quad[2],quad[3]]:
                x,y,z = corners[vertex]
                positions.extend((x,z,-y))
                nx,ny,nz = normal
                normals.extend((nx,nz,-ny))
    position_bytes = struct.pack(f"<{len(positions)}f", *positions)
    normal_bytes = struct.pack(f"<{len(normals)}f", *normals)
    blob = position_bytes + normal_bytes
    axes = [positions[i::3] for i in range(3)]
    document = {"asset":{"version":"2.0","generator":"City Map synthetic sample"}, "scene":0, "scenes":[{"nodes":[0]}], "nodes":[{"mesh":0}], "meshes":[{"primitives":[{"attributes":{"POSITION":0,"NORMAL":1},"material":0}]}], "materials":[{"pbrMetallicRoughness":{"baseColorFactor":[.72,.81,.9,1],"metallicFactor":0,"roughnessFactor":.85}}], "buffers":[{"byteLength":len(blob)}], "bufferViews":[{"buffer":0,"byteOffset":0,"byteLength":len(position_bytes),"target":34962},{"buffer":0,"byteOffset":len(position_bytes),"byteLength":len(normal_bytes),"target":34962}], "accessors":[{"bufferView":0,"componentType":5126,"count":len(positions)//3,"type":"VEC3","min":[min(a) for a in axes],"max":[max(a) for a in axes]},{"bufferView":1,"componentType":5126,"count":len(normals)//3,"type":"VEC3"}]}
    encoded = json.dumps(document, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    length = 12 + 8 + len(encoded) + 8 + len(blob)
    glb = struct.pack("<III", 0x46546C67, 2, length) + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded + struct.pack("<II", len(blob), 0x004E4942) + blob
    (TILES / "buildings.glb").write_bytes(glb)

    lon, lat = map(math.radians, (LON, LAT))
    sl,cl,sp,cp = math.sin(lon),math.cos(lon),math.sin(lat),math.cos(lat)
    n = 6378137 / math.sqrt(1 - 6.69437999014e-3 * sp * sp)
    altitude = campus["altitude"]  # Illustrative placement height, not a surveyed campus elevation.
    transform = [-sl,cl,0,0, -sp*cl,-sp*sl,cp,0, cp*cl,cp*sl,sp,0, (n+altitude)*cp*cl,(n+altitude)*cp*sl,(n*(1-6.69437999014e-3)+altitude)*sp,1]
    tileset = {"asset":{"version":"1.1"},"geometricError":500,"root":{"transform":transform,"boundingVolume":{"box":[15,20,50,150,0,0,0,120,0,0,0,55]},"geometricError":0,"refine":"ADD","content":{"uri":"buildings.glb"}},"extras":{"name":"合成建筑群","source":"人工生成，非真实校园建筑","campus":campus["name"]}}
    (TILES / "tileset.json").write_text(json.dumps(tileset, ensure_ascii=False, indent=2), encoding="utf-8")
    with ZipFile(ROOT / "buildings-demo.zip", "w", ZIP_DEFLATED) as archive:
        for file in sorted(TILES.iterdir()):
            archive.write(file, f"buildings/{file.name}")
    print(f"Generated synthetic campus samples: {campus['name']}")

for campus in CAMPUSES:
    generate(campus)

# Keep the original public download URLs as aliases of the default campus.
default_root = BASE / CAMPUSES[0]["key"]
for name in ("water-points.geojson", "roads.geojson", "areas.geojson", "buildings-demo.zip"):
    shutil.copyfile(default_root / name, BASE / name)
(BASE / "buildings").mkdir(exist_ok=True)
for name in ("tileset.json", "buildings.glb"):
    shutil.copyfile(default_root / "buildings" / name, BASE / "buildings" / name)

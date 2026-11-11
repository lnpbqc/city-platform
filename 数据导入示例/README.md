# 数据导入示例

POI、道路、调查范围和建筑模型均为合成数据，坐标选在大学城附近，方便加入地图后检查位置。可以复制样例，用自己的数据替换其中的记录。

| 文件 | 示例内容 | 接入方式 |
| --- | --- | --- |
| [poi.geojson](poi.geojson) | 图书馆、诊所和换乘站三个地点 | 上传 GeoJSON，图层分类选 `POI` |
| [roads.geojson](roads.geojson) | 四条道路显示线，含道路等级 | 上传 GeoJSON，图层分类选 `道路` |
| [point-line-area.geojson](point-line-area.geojson) | 一个采样点、一条巡查路线、一个调查范围 | 上传 GeoJSON，分类可填 `专题` |
| [network.json](network.json) | 四个节点、四条边及其长度和速度 | 通过后端发布，随后在仿真推演中选择路网版本 |
| [3d-tiles.zip](3d-tiles.zip) | 一组已地理配准的合成建筑 | 整包上传，类型选 `3D Tiles` |

## 在网页上传地图图层

打开「我的数据 → 上传 / 登记数据 → 上传文件」，按表格选择类型和分类。名称可加「示例」前缀，来源填写「合成示例」。登记成功后，在「图层登记」点「加入地图」，再定位图层检查位置和内容。

GeoJSON 使用 UTF-8。顶层 `type` 为 `FeatureCollection`，`features` 中每条记录的 `type` 为 `Feature`。`geometry` 决定形状，`properties` 保存可查询的属性。坐标使用 WGS84，顺序为 `[经度, 纬度]`，可加第三项高程（米）。线至少有两个位置，面环至少有四个位置且首尾相同。

| 样例字段 | 用途 |
| --- | --- |
| POI 的 `name`、`category` | 推荐填写，用于地图名称和类别图标。POI 图层的要素几何为 `Point` |
| POI 的 `address`、`importance` | 可选，分别用于地点卡片和标签显示优先级，权重取数字 |
| 道路的 `highway` | 道路等级，样例使用 `primary` 和 `secondary`。等级影响不同缩放下的显示 |
| 道路的 `edge_id` | 样例自定义字段，可在属性中与 `network.json` 的边 ID 对照 |
| `source` | 样例自定义来源属性，可替换成实际来源 |

## 发布仿真路网

`asset_id` 和 `version` 标识一份路网版本。`nodes` 保存节点 ID 及坐标，`edges` 用 `source`、`target` 引用节点 ID。边 ID 和节点 ID 在各自数组内唯一，`length_m` 与 `speed_mps` 填有限正数，单位分别为米和米每秒。当前仿真使用 `directed: false` 的无向路网，`crs` 填 `EPSG:4326`。样例使用 `synthetic: true` 标注合成数据。

当前网页上传用于地图图层。仿真路网用后端的 `publish_network` 发布。在后端数据库已完成迁移的前提下，用与服务相同的存储配置运行以下 PowerShell 命令。工作目录以 `D:\city` 为例。

```powershell
Set-Location D:\city\map_back
@'
import json
from pathlib import Path
from app.database import SessionLocal
from app.networks import publish_network

path = Path('../数据导入示例/network.json')
document = json.loads(path.read_text(encoding='utf-8'))
with SessionLocal() as session:
    publish_network(session, document)
    session.commit()
print(f"Published {document['asset_id']}@{document['version']}")
'@ | .venv/Scripts/python.exe -
```

发布后，进入「仿真推演」选择 `example-qinghe-network@1.0.0`。可以从 `A` 到 `D`，阻断 `A-B` 后检查 `A → C → D`。修改已发布的路网内容时使用新版本号。

## 查看 3D Tiles ZIP 结构

解开样例 ZIP 后，根目录有两个文件。可在 [3d-tiles 目录](3d-tiles/) 直接查看同一份清单和模型。

```text
3d-tiles.zip
├── tileset.json
└── buildings.glb
```

`tileset.json` 的 `asset.version` 是 3D Tiles 格式版本，`root.boundingVolume` 描述瓦片包围体，`root.transform` 把模型定位到地球上，`root.content.uri` 以相对路径引用模型文件。替换为自己的数据时，用转换工具生成完整瓦片输出，保持所有子目录和相对引用。压缩后的 ZIP 最大 512 MiB，解压总量最大 2 GiB，最多 1,000,000 个归档条目（含目录）。

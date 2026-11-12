# API 1.0 接口说明

本机后端默认地址为 `http://127.0.0.1:8000`，前端通过同源 `/api` 代理访问。完整字段、必填项和响应模型见运行中的[交互文档](http://127.0.0.1:8000/docs)与 [OpenAPI JSON](http://127.0.0.1:8000/openapi.json)。请求和响应模型按业务存放在 [schemas/](../map_back/app/schemas/)。

## 接口速查

路径参数 `{id}` 表示相应资源的实际 ID。除日志和下载外，接口以 JSON 交换数据。

| 资源 | 方法与路径 | 用途 |
| --- | --- | --- |
| 服务 | `GET /api/health`、`GET /api/version` | 健康及服务、API、模型、数据版本 |
| 图层目录 | `GET /api/layers/catalog` | 底图、内置和自定义层的统一目录，含版本、计数、单位和状态 |
| 地图状态 | `PATCH /api/layers/catalog/{id}/map-state` | 保存加入、显隐、透明度及二维顺序 |
| 自定义登记 | `GET /api/layers`、`POST /api/layers` | 列出或创建登记 |
| 自定义登记 | `PATCH /api/layers/{id}`、`DELETE /api/layers/{id}` | 修改完整登记信息或删除登记，文件保留 |
| 自定义状态 | `PATCH /api/layers/{id}/map-state` | 修改自定义层的加入、显隐和透明度 |
| 上传 | `POST /api/layers/upload` | multipart 上传 GeoJSON 或 3D Tiles ZIP，校验后建立资产和登记 |
| POI 快照 | `PUT /api/layers/{id}/poi-data` | multipart 提交 `file`、编辑时的 `asset_id` 和 `version`，发布新的受管快照并更新当前图层 |
| POI 单点变更 | `POST /api/layers/{id}/poi-features` | JSON 提交单点新增、修改或删除，由服务端流式重写新快照 |
| 地图视野 | `POST /api/map/viewport` | 固定资产版本的受控显示副本，携带原始对象身份及截断标志 |
| 附近 POI | `POST /api/map/nearby` | 指定图层版本内按 WGS84 地表距离排序的 POI |
| 地图轻量详情 | `GET /api/map/objects/{id}` | 地点卡片属性及坐标，避免传输完整线面几何 |
| 资产 | `POST /api/assets/register` | 登记 HTTP(S) 或已有受管入口，重复位置返回 409 |
| 资产 | `GET /api/assets`、`GET /api/assets/{id}` | 列表、元信息、文件清单及引用 |
| 资产版本 | `GET /api/assets/{id}/versions`、`GET /api/assets/{id}/versions/{version}` | 固定版本及指纹 |
| 资产 | `DELETE /api/assets/{id}`、`GET /api/assets/{id}/download` | 按引用保护删除，或下载完整资源 |
| 资产对账 | `POST /api/assets/reconcile` | 刷新受管文件目录快照 |
| 统计 | `GET /api/stats/overview` | 资产、对象、运行、容量、类型和七天新增统计 |
| 对象 | `GET /api/objects`、`GET /api/objects/{id}`、`GET /api/objects/summary` | 列表、原始详情、同范围统计 |
| 范围选择 | `POST /api/objects/select` | Polygon 真实相交与裁剪，返回分页对象 |
| 时间 | `GET /api/layers/{id}/times`、`GET /api/timeseries` | 可用时次及固定版本时序值 |
| 路网 | `GET /api/networks`、`GET /api/networks/{id}` | 版本目录与快照；详情可传 `version` |
| 路网校验 | `POST /api/networks/{id}/validate` | 结构与连通性诊断，可传 `version` |
| 场景 | `GET /api/scenes`、`POST /api/scenes`、`GET /api/scenes/{id}` | 场景列表、创建和详情 |
| 场景 | `PUT /api/scenes/{id}`、`DELETE /api/scenes/{id}` | 带 `If-Match` 完整替换或删除 |
| 运行 | `POST /api/runs`、`GET /api/runs`、`GET /api/runs/{id}` | 提交、历史列表与状态 |
| 运行控制 | `POST /api/runs/{id}/cancel`、`POST /api/runs/{id}/rerun` | 取消或按旧快照重跑 |
| 运行删除 | `DELETE /api/runs/{id}` | 删除终态运行及其输入、结果、日志，释放运行资产引用；不删除源数据 |
| 运行内容 | `GET /api/runs/{id}/input`、`GET /api/runs/{id}/logs`、`GET /api/runs/{id}/result` | 固定输入、UTF-8 日志和成功结果 |
| 运行导出 | `GET /api/runs/{id}/download?format=json` | 下载 JSON；另支持 `format=geojson` |
| 运行对账 | `POST /api/runs/reconcile` | 补缺失镜像，报告改动及孤立内容 |
| 收藏 | `GET /api/bookmarks`、`POST /api/bookmarks` | 地区、点位和工作区收藏 |
| 收藏 | `PATCH /api/bookmarks/{id}`、`DELETE /api/bookmarks/{id}` | 改名或删除，保留关联场景和运行 |

## 通用规则

POI 导入使用现有上传接口，设置 `category=POI` 和 `type=geojson`，文件须为 WGS84 Point 要素集合，空集合用于创建空 POI 图层。GeoJSON 上传及兼容 POI 快照接口上限为 1 GiB（1,073,741,824 字节），成功返回更新后的图层登记。若编辑时的资产引用已过期，返回 `409 POI_SNAPSHOT_CONFLICT`，客户端应重新加载后编辑。此前发布的文件与已有场景的固定引用继续有效。

- JSON 使用 UTF-8。接口时间须带时区并按 UTC 输出；GeoJSON 使用 WGS84 经纬度，可选高程为米。相机位置经纬度为度、高度为米，`heading/pitch/roll` 为弧度。
- 资产引用形如 `{"asset_id":"net-001","version":"1.0.0"}`。发布版本不可变，与 `tileset.json` 的格式版本独立。
- 分页结构为 `{"items":[],"total":0,"page":1,"page_size":20}`，默认每页 20、最多 100；`total` 为筛选后、分页前数量，排序包含稳定 ID。
- `GET /api/assets` 只有显式传 `page` 或 `page_size` 才返回分页结构，否则保留旧数组。图层目录、自定义图层和收藏列表也返回数组；对象、场景、路网、运行使用分页。
- 未知体积、范围、语义、置信度和数值使用 `null`，真实数值 0 保留。
- HTTP 头 `X-Trace-ID` 与错误体 `trace_id` 对应服务请求日志；场景响应另提供 `ETag`。

### 错误

```json
{"code":"ASSET_IN_USE","message":"资产被场景引用","detail":{"references":[{"type":"scene","id":"scene-example","name":"示例场景","version":1,"asset_version":"1.0.0"}],"reference_count":1},"trace_id":"示例诊断ID"}
```

`detail` 保留字符串、数组或对象的原有形状。

| HTTP | 常见 code | 处理依据 |
| --- | --- | --- |
| 400 | `INVALID_ARGUMENT`、`IF_MATCH_REQUIRED`、`INVALID_IF_MATCH`、`INVALID_IDEMPOTENCY_KEY` | 参数格式或必需请求头 |
| 403 | `FORBIDDEN`、`ASSET_PROTECTED` | 访问条件或默认资源保护 |
| 404 | `ASSET_NOT_FOUND`、`ASSET_VERSION_NOT_FOUND`、`LAYER_NOT_FOUND`、`OBJECT_NOT_FOUND`、`SCENE_NOT_FOUND`、`NETWORK_NOT_FOUND`、`RUN_NOT_FOUND` | 资源及固定版本是否存在 |
| 409 | `ASSET_IN_USE`、`ASSET_ALREADY_REGISTERED`、`ASSET_CONTENT_CHANGED`、`ASSET_UNAVAILABLE`、`OBJECT_INDEX_UNAVAILABLE`、`POI_SNAPSHOT_CONFLICT`、`SCENE_VERSION_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`RUN_TERMINAL` | 引用、资源状态、版本或幂等冲突 |
| 413 | `PAYLOAD_TOO_LARGE` | 上传或解压总量超限 |
| 422 | `VALIDATION_ERROR`、`CONTENT_INVALID`、`INVALID_NODE`、`INVALID_EDGE`、`ORDER_UNSUPPORTED` | 字段、几何、正式边及排序条件 |
| 500 | `INTERNAL_ERROR` | 按诊断 ID 查询后端日志 |

字段校验使用 `VALIDATION_ERROR`，文件内容校验通常使用 `CONTENT_INVALID`；其他业务错误按具体 code 处理。前端网络或响应体断流使用 `NETWORK_ERROR` 与 `client-` 诊断 ID，解析失败使用 `INVALID_RESPONSE`。网络错误时，写入结果可能未知，重试须遵循幂等规则。

## 图层、资产与引用

目录参数 `campus=university-town|huangpu` 选择默认资源，默认大学城；切换校区共用默认图层状态，替换对应资产绑定。`category` 为 1 至 80 字的分类字符串；预置分类包含底图、建筑、道路、POI、水体、专题、仿真结果，自定义分类原样返回并独立分组。旧三维建筑、三维模型、线状网络别名保持兼容。

地图状态字段为 `map_attached/map_visible/map_opacity`。目录状态接口的 `order` 是从 0 开始的完整目录目标位置，较小值显示更靠前；后台原子重排。排序仅支持已核对的二维 GeoJSON，三维瓦片、拉伸面、含 Z 几何及未知远端资源返回 `orderable=false`，调整顺序返回 422。

3D Tiles 高度设置包含 `tiles_align_to_terrain`（可空布尔值）、`tiles_height_offset_m`（有符号米值，默认 0）和 `tiles_ground_anchor`（可空手动锚点，包含 WGS84 `longitude`、`latitude` 及原始椭球高 `height`，高程单位为米）。开启对齐时优先使用手动锚点，空锚点使用固定版本模型的原点。`false` 关闭对齐并继续应用手动偏移。PATCH 省略字段时保留已保存值。内置三维模型按 `campus` 保存高度设置。

普通图层的对齐开关缺省或为 `null` 时按开启处理。旧场景的对齐开关缺省或为 `null` 时，有锚点沿用锚点，无锚点按原始高度加偏移恢复。新保存的 3D Tiles 场景状态包含明确的开关、锚点和偏移。

上传字段与限制以实时 Schema 和[数据与模型说明](数据与模型说明.md)为准。`POST /api/assets/register` 的 `location` 接受 HTTP(S) 或已有 `/data-files/` 入口；原始磁盘路径不开放。外部资源只记录元信息，`ready` 表示登记可用，实际渲染取决于浏览器和远端服务。

资产列表支持 `type/status/q/from/to/sort`；关键词按字面匹配 ID、名称、原文件名及来源，日期须带时区并包含端点。`sort=byte_size|-byte_size` 按体积排序，未知外部体积置末。分页列表和统计读取目录快照，详情检查实际文件；显式对账刷新磁盘变化。旧数组模式在未提供筛选或排序时逐项检查文件。

| 来源 | 状态与删除行为 |
| --- | --- |
| 默认资产 | `source_kind=default, protected=true`，实体禁止删除，允许移除地图或登记 |
| 上传资产 | 解除全部引用后删除台账与文件 |
| 外部资产 | 解除引用后只删除台账 |

资产响应以 `current_version` 表示当前版本，图层以 `asset_version` 固定绑定。改名或扫描保持既有绑定。版本状态为 `ready/missing/unsafe`；旧资产状态为 `active/deleting/delete_error/missing/unsafe`，其中 `active` 对应可用版本 `ready`。

`file_checksums` 保存逐文件大小与 SHA-256；资产 `sha256` 是按相对路径排序的 `[{path,size,sha256},...]` 清单经规范 JSON 序列化后的摘要。路径分隔符为 `/`，外部未知内容为 null。发布后的指纹保持不变；扫描发现内容变化标为 unsafe，下载核对源文件及输出快照。

`bounds` 为 WGS84 西、南、东、北及可选高程，跨日期变更线允许 west 大于 east。统计只计算可测得的本地容量；对象数取可用资产当前版本，同资产多个登记计一次，历史版本元信息保留。

删除冲突返回逐版本引用明细。`type=scene` 包含场景 ID、名称、版本和资产版本，`type=run` 包含运行 ID 及快照信息；旧图层引用保留 `id/name`。独立引用者数量与明细条数分别计算，同一场景引用两个版本对应一个场景、两条明细。

## 对象与空间查询

GeoJSON 对象 ID 由资产 ID、版本和原始 Feature 序号生成 UUID5；重复原生 Feature ID 也能定位。`feature_index` 从 0 开始，`properties` 保留原始属性，缺少名称、高度、等级或置信度时返回 null。

列表和统计支持 `asset_id/version/layer_id/type/q/bbox/time/resolution/campus`，列表另含分页。默认读取可用资产的当前版本；按图层读取其固定版本，绑定冲突返回 422。`q` 按字面搜索对象 ID、名称和属性，`type` 精确匹配。

`bbox=west,south,east,north` 真实相交并裁剪几何，west 大于 east 时覆盖日期变更线两侧。多边形选择示例中的资产 ID 需替换为实际值：

```json
{"geometry":{"type":"Polygon","coordinates":[[[113,23],[114,23],[114,24],[113,23]]]},"asset_id":"实际资产ID","page":1,"page_size":20}
```

同时给 bbox 时取交集。多边形包含空洞与边界计算，未闭合、自交或坐标非法返回 422。裁剪后的代表点用于定位；详情返回完整原始几何。统计计算对象数、WGS84 椭球面积及已有高度范围；列表与统计使用相同筛选和裁剪规则，各次请求分别使用一致读快照。裁剪到线或点的原面面积为 0。

普通 3D Tiles 返回一个 `type=model, semantic_source=geometry_model` 的模型资源对象，`feature_index/geometry` 为空。缺少可查询几何的资源不参与范围筛选；外部对象索引不可用返回 409 `OBJECT_INDEX_UNAVAILABLE`，本地资产异常返回 `ASSET_UNAVAILABLE`。

传 `time/resolution` 时，对象附 `temporal={time,resolution,unit,value,missing}`，静态对象为 null，原属性保持。分辨率默认 hour，可选 day。

## 地图视野与 POI

`POST /api/map/viewport` 请求绑定图层和资产版本，例如：

```json
{"layer_id":"实际图层ID","asset_id":"实际资产ID","version":"1.0.0","campus":"university-town","bbox":[113.3,23.0,113.4,23.1],"width":1280,"height":720}
```

`bbox` 按西、南、东、北排列，支持跨日期变更线；`width/height` 为 1 至 16,384 的画布像素尺寸。可选 `meters_per_pixel` 为正有限地面米/像素，缺省按视野范围估算。响应为 `FeatureCollection`，另含 `truncated`。每个 Feature 的 `id` 为原始对象 UUID，`__object` 包含 `object_id/feature_index/asset/weight`，`properties` 保留原属性。显示序号不得用于重新生成对象 ID。单次每图层最多 2,000 个要素、100,000 个顶点、10 MiB；`truncated=true` 时客户端提示放大。道路仅裁剪及清理完全重复坐标，保留所有转折；普通非道路线面继续允许显示简化，原始几何可由原对象接口读取。

道路先按比例尺筛选。名称、编号和桥隧层级等属性兼容的二度连接线段组成显示线组，再按等级用完整线组应用预算。放不下的线组整组省略，并返回 `truncated: true`。其 `id` 为代表来源对象 UUID，`__object.source_object_ids` 列出原始分段，`__display.road_class/road_rank` 提供制图等级。`POST /api/map/road-pick` 接收同一图层引用、`object_ids`（最多 2,000 项）及 `longitude/latitude`，返回距离点击位置最近的原始对象和原始几何。分析路网仍使用原始分段。

POI 先按中文类别、有效名称和比例尺确定背景显示资格，再在完整候选范围按显式权重、语义优先级和稳定 ID 选择候选。权重取 `importance/weight/priority` 首个有效数值，默认 0；每个空间格可提供多个候选，由前端统一避让。`__display.poi_category/priority/name` 提供显示类别、语义优先级和有效名称。附近查询独立于背景资格与显示抽稀：

```json
{"layers":[{"layer_id":"实际POI图层ID","asset_id":"实际资产ID","version":"1.0.0"}],"longitude":113.366746,"latitude":23.043612,"radius_m":1000,"limit":20}
```

`POST /api/map/nearby` 的 `layers` 最多 100 项，由客户端提交已加入且已开启的 POI 图层；每项可指定 `campus`。半径默认且最大 1,000 米，数量默认且最大 20。返回 `{"items":[],"unavailable_layers":[]}`；对象含 `layer_id` 和 `distance_m`，按 WGS84 地表距离升序、对象 ID 稳定排序。抽稀隐藏点参与查询；无可用本地索引的图层列于 `unavailable_layers`，客户端须提示未参与查询。

`GET /api/map/objects/{id}` 返回轻量对象字段，Point 保留点几何供编辑，线面 `geometry=null`，保留原属性、坐标及 `feature_index`。已有 `GET /api/objects/{id}` 继续返回完整原始几何。

`POST /api/layers/{id}/poi-features` 使用编辑时的预期引用和单点操作：

```json
{"asset_id":"编辑时的资产ID","version":"1.0.0","operation":"update","object_id":"实际对象UUID","feature":{"type":"Feature","geometry":{"type":"Point","coordinates":[113.366746,23.043612]},"properties":{"name":"示例地点","category":"餐饮","address":"示例路"}}}
```

`operation` 为 `add/update/delete`；修改、删除须指定 `object_id`，新增、修改须指定 Point `feature`。服务端保留未改属性及原文件其他字段，变更后流式生成新快照并返回图层登记。接口仅支持本地上传、未受保护的 POI 图层；提交及最终发布均检查预期资产/版本，冲突返回 `409 POI_SNAPSHOT_CONFLICT`。新建图层仍使用上传接口。

## 路网、场景与并发


路网目录按 ID、发布时间倒序及版本分页；详情省略版本时选择最新可用发布版本。读取异常快照返回 409 `NETWORK_INVALID`，校验接口仍返回 200 和 `valid=false/issues`，问题包含具体 `node_ids/edge_ids`。

路网为无向 EPSG:4326，节点坐标为经纬度及可选米制高程，边 `length_m/speed_mps` 为有限正数。校验重复节点、重复或反向重复边、自环、缺失节点、孤立点与连通分量。发布逻辑位于 `networks.py`，同 ID 同版本同内容幂等，内容变化需新版本；当前 HTTP 接口提供查询和校验。

场景保存相机、图层、路网、起终点、阻断边、参数、种子、当前时刻和运行引用。图层包含 `layer_id/asset/map_attached/map_visible/map_opacity/order`；底图 asset 为 null，其余层固定有效资产版本。场景保存独立于全局图层状态；删除全局登记后，场景保留旧绑定和引用。

创建场景返回 201、版本 1 和 `ETag: "1"`。PUT 完整替换、DELETE 删除均要求 `If-Match: "当前版本"`；缺失返回 400 `IF_MATCH_REQUIRED`，格式错误返回 400 `INVALID_IF_MATCH`，过期返回 409 `SCENE_VERSION_CONFLICT` 并附 `current_version`。并发使用同版本更新仅一次成功，成功更新版本加一，删除成功返回 204。

场景只保存当前版本。`GET /api/scenes/{id}?version=1` 校验当前版本是否为 1，变化返回 409，已删除返回 404。`GET /api/scenes` 支持可选 `q` 参数，按名称包含或完整场景 ID 匹配后分页。完整 ID 匹配优先，其余按更新时间倒序和 ID 排列。删除带收藏引用的场景返回 409 `SCENE_BOOKMARKED`，解除收藏后可重试。历史运行独立保留。

场景可保存未选择路网或未完成起终点的草稿；已填写字段必须有效，提交运行时起终点必须完整。未知字段拒绝，阻断正式边去重排序，`run_id` 必须存在。场景解除或删除释放自身引用，历史运行引用继续保护资产。

## 运行、幂等与结果

提交前先通过界面或场景 API 创建场景。请求示例中的 `scene_id` 替换为实际 ID：

```json
{"scene_id":"实际场景ID","network":{"asset_id":"net-001","version":"1.0.0"},"origin":"S","destination":"T","blocked_edges":["B-T"],"params":{"mode":"car"},"seed":0}
```

提交原子读取当前场景版本，保存 `request/scene/model_version/data_version` 快照。请求的路网和路径参数用于本次计算；非法节点或正式边返回 422，校验通过后才创建运行。

### 幂等与输入哈希

`Idempotency-Key` 去除首尾空格后长度为 1～200 字符。首次创建返回 201；同键同规范输入返回 200 和原 run_id，同键不同输入或场景版本返回 409 `IDEMPOTENCY_CONFLICT`。省略键或使用新键可创建新运行。

提交响应未知时复用相同键和请求体，并保持场景版本；先更新场景会改变输入哈希。自动重连恢复读取，前端由“重试同一次提交”确认未知写入。

`inputs_sha256` 的哈希对象为规范请求、场景输入、`scene_version/model_version/data_version`：阻断边去重排序，场景图层按 `order/layer_id` 排序，补齐参数默认值。场景 ID、版本和时间元数据及 run_id 从场景正文移除，版本另存于哈希对象；请求仍含 scene_id。运行 ID、运行时间、幂等键和 trace_id 不参与哈希。

规范 JSON 采用 UTF-8、递归键排序、紧凑分隔符、不转义中文、拒绝 NaN/Infinity，SHA-256 输出小写十六进制。实现见 [run_store.py](../map_back/app/services/run_store.py) 和 [run_artifacts.py](../map_back/app/services/run_artifacts.py)。

### 状态、取消与恢复

`DELETE /api/runs/{id}` 成功返回 204，重复删除仍返回 204；只允许 `succeeded/failed/cancelled`，活动运行返回 `409 RUN_NOT_TERMINAL`。场景或收藏仍引用该运行时返回 `409 RUN_IN_USE`，`detail.references` 列出引用来源。删除和结果文件发布共享锁，提交前的文件清理或数据库提交失败会恢复原记录和目录；提交后的隔离恢复副本清理失败会记录日志，由启动或运行对账重试。源资产和其他历史运行不受影响。

历史图层读取按场景或运行快照验证固定资产引用；旧登记或原场景已删除但资产仍存在时可以继续恢复。新快照可携带图层 `name/category`，旧快照省略这些字段时保持原输入哈希。

状态为 `queued → running → succeeded/failed/cancelled`，排队任务可直接取消；运行中取消等待计算子进程退出后记录终态及结束时间，终态取消返回 409 `RUN_TERMINAL`。

队列在单个 uvicorn 进程中按提交时间和 ID 领取任务。模型计算超过 60 秒记录 `failed/RUN_TIMEOUT`；正常停服中断记录 `SERVICE_STOPPED`，异常重启将遗留 running 记录为 `failed/RUN_INTERRUPTED` 并继续 queued。记录包含输入哈希、模型与数据版本、场景版本、时间、耗时、错误及首次提交的 trace_id。

历史列表支持 `scene_id/status/from/to`，日期须带时区，端点包含，from 晚于 to 返回 422；按提交时间倒序及 ID 分页。

### 结果、镜像与重跑

模型 `dijkstra-undirected-v1` 按显式长度求最短路，等长按完整节点序列字典序选择，预计秒数逐边累计。内置路网与三种验证情形见[数据与模型说明](数据与模型说明.md)和[功能说明](功能说明.md)。

不可达返回 `reachable=false,path=[],length_m=null,duration_s=null`，仍为成功结果；同起终点返回单节点路径、0 米和 0 秒。基准不可达或长度为 0 时增幅为 null；两条路线均可达且节点序列不同时 `rerouted=true`。绕行结果结构：

```json
{"run_id":"示例运行ID","baseline":{"path":["S","A","B","T"],"length_m":660,"duration_s":66,"reachable":true},"blocked":{"path":["S","A","C","D","T"],"length_m":960,"duration_s":96,"reachable":true},"metrics":{"increase_percent":45.45454545454545,"rerouted":true},"created_at":"2026-10-25T04:00:01Z"}
```

数据库提交后生成 `storage/runs/{run_id}/input.json`、成功结果 `result.json` 和 `run.log`。缺失镜像可由对账重建，内容不一致返回 409 `RUN_ARTIFACT_CHANGED` 并保留文件；孤立结果、目录分别报告 `ORPHAN_RUN_RESULT/ORPHAN_RUN_DIRECTORY`。日志接口读取数据库记录，JSON 下载字节与规范结果镜像一致，GeoJSON 导出路径及实际阻断边并附版本和哈希。

`POST /api/runs/{id}/rerun` 使用空请求体，复制原始快照、哈希和资产引用，新键创建新 run_id。原场景修改或删除后仍可重跑，原运行及成功结果保留；旧模型不可执行返回 409 `MODEL_VERSION_UNAVAILABLE`。幂等键在提交和重跑之间全局共用。

运行独立保存资产引用，删除场景、图层或取消运行均保留历史引用。

## 时序与工作区收藏

### 时序

`GET /api/layers/{id}/times` 返回按 UTC 升序排列的时间字符串数组，静态层为 `[]`；支持 `asset_id/version/campus`。`GET /api/timeseries` 必填 `layer_id/time`，可传 `resolution=hour|day`、bbox 和相同版本参数。

快照以资产版本、时刻和对象 ID 固定，查询只读。hour 精确命中请求时次；day 按 `Asia/Shanghai` 自然日对已有非空小时值取均值，返回当天北京时间零点对应的 UTC。缺少快照返回 409 `TIMESERIES_UNAVAILABLE`，未知图层/版本返回 404，错绑或无时区时间返回 422。

`TimeSeriesOutput` 包含 `layer_id/asset/time/resolution/unit/items`。有值项返回原几何或 bbox 裁剪几何，缺测项返回 `geometry=null,value=null,missing=true`；真实 0 为 `value=0,missing=false`。静态图层保持原资源，动态更新仅调整专题实体与属性。

### 收藏与链接

收藏支持 `kind=region|point|scene`。地区和点位沿用位置字段，`state=null`；工作区收藏位置字段为 null，state 保存 `page/scene_id/scene_version/run_id/time/resolution/camera/comparison`，page 为 map 或 simulation，comparison 仅供地图双视图使用。

创建前由前端保存独立场景，后端在同一写事务校验场景、版本与运行；`state.run_id` 须与捕获场景一致。冲突返回 409 `SCENE_VERSION_CONFLICT`，错误运行返回 422 `RUN_NOT_FOUND/SCENE_RUN_MISMATCH`。改名保留状态和创建时间，删除收藏保留场景及运行；失效引用继续出现在列表供诊断。

已捕获场景保留的旧图层绑定可通过 `layer_id/asset_id/version` 查询对象与时序，服务核对该场景的图层及资产引用；没有对应引用的错绑仍返回 422。

前端链接参数包括 `scene/v/run/t/resolution/camera/compare_t/compare_resolution`，位于 URL 查询部分，页面由 hash 指定。生成链接使用 UTC；读取无时区 t 时按北京时间解释，传给后端前转换为带时区时间。链接解析及生成见 [workspaceState.ts](../map/src/router/workspaceState.ts)。

## 完整 GeoJSON、显示归档与原文件保留

本地 GeoJSON 上传成功后，完整快照与对象索引在同一事务提交。完整快照保存原始几何、属性、要素 `id`、外来成员及集合元数据，并保留 `properties=null` 与空对象的区别。对象身份由资产、固定版本和原始 `feature_index` 决定，不随视野筛选或显示抽稀改变。

| 接口 | 行为 |
| --- | --- |
| `GET /api/assets/{asset_id}/versions/{version}/geojson` | 按原始索引顺序、固定批次流式导出完整快照，返回 `application/geo+json` 和下载文件名 `data.geojson` |
| `GET /internal/render-source/{asset_id}/{version}` | 供切片服务读取相同版本输入，须携带 `Authorization: Bearer {CITY_TILE_TOKEN}`；每个要素临时增加 `__object={object_id,feature_index}` |
| `GET /api/assets/{asset_id}/versions/{version}/render` | 返回显示任务描述，无任务时返回 null；可通过 `category` 选择显示配置 |
| `POST /api/assets/{asset_id}/versions/{version}/render/retry` | 重试失败或已取消任务；可传 `category`，不适用的版本返回 409 `RENDER_NOT_APPLICABLE` |
| `POST /api/assets/{asset_id}/versions/{version}/render/cancel` | 取消排队或执行中的显示任务，地图继续使用当前视野接口 |
| `GET /api/render-files/{key}/map.pmtiles` | 下载已发布 PMTiles，支持 Range 和 ETag；归档整体不使用 gzip 编码 |
| `POST /api/map/road-groups` | 接收图层引用、`render_key` 和最多 2,000 个原始 `object_ids`，返回对应的 `groups=[{group_id,object_ids}]`；用于框选原始路段后高亮合并显示线，校验资产版本归属 |
| `GET /api/stats/storage` | 返回源文件、显示产物、数据库和临时文件的物理空间分项，与事务一致的目录统计分开读取 |

导出保留 GeoJSON 语义，不保证与上传文件字节一致。内部输入的 `__object` 仅用于传输对象身份；原要素中同名的用户数据仍保留在完整快照及公开导出中。未知或不可用版本返回 404 `ASSET_VERSION_NOT_FOUND`，尚无已验证完整快照返回 409 `SNAPSHOT_UNAVAILABLE`；内部凭据缺失或错误返回 401。

显示描述包含 `key/status/stage/error/profile/recipe/manifest/url/byte_size/source_state/source_expires_at`。只有 `status=succeeded` 时提供归档 URL。显示配置固定为版本化 recipe，同一来源版本、profile 和 recipe 复用任务；用户选择的道路显示等级不改变产物键。

适用的本地上传普通 GeoJSON 首次成功发布显示产物后，设置七天原文件保留期。重试不延长该版本期限。清理前须确认完整快照和显示产物可用；失败、排队或迁移未验证的数据保留原文件。默认资源、外部资源、建筑拉伸、时序和 3D Tiles 不参与自动清理。

清理后 `source_state=expired`。`GET /api/assets/{asset_id}/download` 返回 410 `SOURCE_EXPIRED`，完整 GeoJSON 导出、对象查询及 POI 编辑继续使用完整快照。原文件到期不将资产标记为 missing。删除资产仍受图层、场景和历史运行引用保护；成功删除会取消显示任务并清理正式产物。

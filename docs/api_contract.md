# API 1.0 契约

本契约定义已接入接口的字段与边界，Python定义位于`map_back/app/contracts.py`，完整运行时Schema见[交付OpenAPI](delivery/openapi.json)。本机单用户运行，沿用FastAPI、SQLite与旧接口。

## 通用规则

- JSON 使用 UTF-8。时间采用带时区的 ISO 8601；前端按本地时区显示。GeoJSON 使用 WGS84，经度在前、纬度在后、高程为米。
- 资产引用固定为 `{"asset_id":"net-001","version":"1.0.0"}`。版本发布后不可变，与 `tileset.json` 的 `asset.version` 独立。旧资产 ID、文件地址与物理目录保留。
- `GET /api/assets` 未传 `page`、`page_size` 时保留旧数组；显式传任一个分页参数时返回 `Page[AssetOutput]`，保留现有资产字段并补充版本与元信息，默认 `page=1&page_size=20`，单页最多 100 条。新对象、场景、路网和运行列表使用同一分页结构。
- 分页返回 `{"items":[],"total":0,"page":1,"page_size":20}`。`total` 是筛选后、分页前的数量。排序必须追加 ID 作为稳定次序，避免相同值导致遗漏。
- 资产分页、筛选、排序及统计使用最近上传或对账时的目录快照；通过 `POST /api/assets/reconcile` 刷新磁盘变更，详情继续检查实际文件。未传任何列表参数时保留原数组与文件检查行为。`q` 按字面搜索ID、名称、原文件名、来源；`from/to` 为带时区的时间，按UTC比较并包含端点，上传时间优先、否则用发现时间；`status=ready` 等同旧状态active。体积排序将外部未知容量始终置末。
- 未知体积、范围、语义、置信度和值均使用 `null`；真实数值 0 保留为 0。对象缺语义时使用 `semantic_source="geometry_model"`，页面显示“该瓦片未携带语义属性，来源：几何模型”。瓦片不计作独立建筑。

## 错误与服务版本

错误体为 `ErrorEnvelope`；`detail` 保留既有字符串、数组或对象形状，供旧客户端继续读取。`trace_id` 与响应头 `X-Trace-Id`、服务日志一致。

```json
{"code":"ASSET_IN_USE","message":"资产被场景或运行引用","detail":{"references":[{"type":"scene","id":"s1","version":1}],"reference_count":1},"trace_id":"trace-id"}
```

| HTTP | code | 用途 |
| --- | --- | --- |
| 400 | `INVALID_ARGUMENT` | 请求参数或格式错误 |
| 403 | `FORBIDDEN`、`ASSET_PROTECTED` | 访问受限、默认资产禁止实体删除 |
| 404 | `ASSET_NOT_FOUND`、`ASSET_VERSION_NOT_FOUND`、`LAYER_NOT_FOUND`、`OBJECT_NOT_FOUND`、`BOOKMARK_NOT_FOUND`、`NOT_FOUND` | 资源或版本不存在 |
| 409 | `CONFLICT`、`ASSET_IN_USE`、`ASSET_ALREADY_REGISTERED`、`ASSET_CONTENT_CHANGED`、`ASSET_UNAVAILABLE`、`OBJECT_INDEX_UNAVAILABLE`、`EXTERNAL_ASSET`、`SCENE_VERSION_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`RUN_TERMINAL` | 引用保护、重复登记、内容变化、不可用资产或索引、外部地址下载限制、乐观锁、幂等键冲突、终态取消 |
| 413 | `PAYLOAD_TOO_LARGE` | 上传体积超限 |
| 422 | `VALIDATION_ERROR`、`INVALID_EDGE`、`CONTENT_INVALID`、`ORDER_UNSUPPORTED` | 字段、路网边、文件内容不合规，或图层不支持二维顺序调整 |
| 500 | `INTERNAL_ERROR` | 未预期异常；详情与堆栈写入服务日志 |

字段校验返回`VALIDATION_ERROR`，已有文件内容校验返回`CONTENT_INVALID`；各资源通过域错误指定具体code。前端连接失败或响应体断流显示`NETWORK_ERROR`与`client-`开头的诊断ID，此时请求结果可能尚未确认；响应内容解析失败使用`INVALID_RESPONSE`。客户端诊断ID用于前端排查，服务trace_id对应后端日志。顶部“请求诊断”可复制code、message和trace_id。

`GET /api/version` 返回 `VersionOutput`。当前示例为 `{"service_version":"0.2.0","model_version":"dijkstra-undirected-v1","data_version":"net-001@1.0.0","api_version":"1.0"}`。运行记录始终保存实际使用的模型与数据版本。

## 资源接口与输入输出

| 资源 | 接口 | 契约与行为 |
| --- | --- | --- |
| 资产 | `POST /api/assets/register` | `AssetRegisterInput` → `AssetVersionOutput`，201；重复位置登记 409。`location` 支持 HTTP(S) URL 或已受管的 `/data-files/` 入口，登记不搬文件；原始磁盘路径不开放 |
| 资产 | `GET /api/assets`、`GET /api/assets/{id}` | 保留 `AssetOutput/AssetDetail` 的既有字段、文件清单及引用信息，并补充版本与元信息；列表支持 `type/status/q/from/to/sort`，`sort` 为 `byte_size` 或 `-byte_size`，默认按创建时间倒序 |
| 资产版本 | `GET /api/assets/{id}/versions`、`GET /api/assets/{id}/versions/{version}` | 返回版本列表及 `AssetVersionOutput`；旧资产默认初始版本为 `1.0.0` |
| 资产 | `DELETE /api/assets/{id}`、`GET /api/assets/{id}/download` | 场景和运行按版本引用，冲突 409 并给引用数量及明细；下载保留入口、相对文件路径与逐文件内容 |
| 图层 | `GET /api/layers/catalog` | `list[LayerCatalogOutput]`；旧 `/api/layers` 继续供现有自定义图层 CRUD 使用 |
| 图层状态 | `PATCH /api/layers/catalog/{id}/map-state` | 默认与自定义图层共用显隐/透明度/加入状态；`order`为从0开始的目标位置，原子调整目录顺序 |
| 对象 | `GET /api/objects`、`GET /api/objects/{id}` | `Page[ObjectOutput]`、`ObjectOutput`；支持 `asset_id/version/layer_id/bbox/type/q/time` |
| 对象 | `POST /api/objects/select` | 输入 GeoJSON Polygon 及与列表相同筛选条件，输出 `Page[ObjectOutput]`，用于框选/多边形选择 |
| 对象 | `GET /api/objects/summary` | `ObjectSummary`；与对象列表使用相同筛选和裁剪逻辑，面积/高度未知时为 null |
| 场景 | `POST /api/scenes`、`GET /api/scenes`、`GET /api/scenes/{id}` | `SceneInput` → `SceneOutput`，创建 201；列表为 `Page[SceneOutput]`；详情可传 `version>=1` 校验固定版本，不符返回 409 |
| 场景 | `PUT /api/scenes/{id}` | 完整 `SceneInput` 替换，要求 `If-Match: "1"`；成功版本加一，响应 `ETag: "2"`；缺失或错误格式 400，过期版本 409 |
| 场景 | `DELETE /api/scenes/{id}` | 要求当前`If-Match`，成功204并释放该场景的资产引用 |
| 收藏 | `GET /api/bookmarks`、`POST /api/bookmarks` | 列表保留数组，创建返回 201；支持 `region/point/scene`，工作区以 `state: WorkspaceState` 引用固定场景版本 |
| 收藏 | `PATCH /api/bookmarks/{id}`、`DELETE /api/bookmarks/{id}` | PATCH 仅修改名称；删除返回 204，关联场景、运行及其资产引用保留 |
| 路网 | `GET /api/networks`、`GET /api/networks/{id}?version=1.0.0` | `Page[NetworkOutput]`、`NetworkOutput`；版本省略时解析为最新可用不可变版本 |
| 路网 | `POST /api/networks/{id}/validate?version=1.0.0` | `NetworkValidationOutput`；检查孤立点、连通分量、重复无向边、非法权重和缺失节点；问题包含节点/边 ID |
| 运行 | `POST /api/runs`、`GET /api/runs`、`GET /api/runs/{id}` | `RunInput` → `RunOutput`，首次创建 201、幂等重放 200；列表 `Page[RunOutput]`，支持 `scene_id/status/from/to` |
| 运行 | `POST /api/runs/{id}/cancel` | 返回 `RunOutput`；终态取消 409 |
| 运行重跑 | `POST /api/runs/{id}/rerun` | 空请求体，固定旧快照与哈希；新run_id返回201，同幂等键同哈希200，旧模型不可执行409 |
| 运行 | `GET /api/runs/{id}/input`、`GET /api/runs/{id}/logs` | 固定`RunInputSnapshot`、UTF-8纯文本状态日志 |
| 运行 | `POST /api/runs/reconcile` | 核对私有文件，补齐缺失镜像，报告已修改文件及孤立目录/结果 |
| 运行 | `GET /api/runs/{id}/result`、`GET /api/runs/{id}/download?format=json` | `RunResult`；未成功返回 409；下载支持 `json/geojson`；成功结果只读 |
| 时序 | `GET /api/layers/{id}/times` | `LayerTimesOutput`，返回时间字符串数组 `[]` 或 `["2026-10-25T00:00:00Z"]`，按时间升序 |
| 时序 | `GET /api/timeseries` | `TimeSeriesOutput`；参数 `layer_id/time/resolution/bbox`，`resolution=hour/day` |
| 统计 | `GET /api/stats/overview` | `StatsOverview`；容量统计可测得的本地文件，未知外部体积不计入且详情为 null |

默认资产 `source_kind="default"`、`protected=true`；允许移除图层/登记，实体文件始终保留。上传资产解除引用后可删除文件；外部 URL 仅删除登记。新资产版本使用 `ready/missing/unsafe`，旧资产接口继续保留 `active/deleting/delete_error/missing/unsafe`，旧 `active` 对应新可用版本 `ready`。

图层目录已接入底图与两校区既有样例，`campus=university-town/huangpu`选择默认资源绑定，默认大学城；保留原图层ID与样例URL。默认显隐、透明度、加入状态与顺序跨校区共用，切换校区只替换默认资源；已移除的资源仍留在目录。响应补充builtin、campus、source、map_attached/map_visible/map_opacity及order。分组固定为底图/建筑/道路/水体/专题/仿真结果，空分组由页面显示空态；自定义未知分类归入专题，未知单位与图例为null/空数组。

排序仅开放给本地已核对的二维GeoJSON；瓦片、拉伸多边形、带Z坐标及未读取的远端几何返回orderable=false，调整顺序返回422 ORDER_UNSUPPORTED。显隐和透明度适用于这些资源。默认点/线/面的单位分别为cm、辆/小时、cm，来自现有属性；建筑长度单位为m。对象数量来自当前可用版本的对象索引，底图为0，未读取的外部资源或不可用资产为null。地图已使用统一目录恢复默认与自定义状态，并按固定版本入口加载；六类图层树、计数、单位和排序控件均已接入页面。较小order表示二维叠加层更靠前显示，上移/下移寻找相邻已加入的可排序层，提交其完整目录位置；三维绘制始终保留深度测试。

当前统计已接入资产数量、类型、容量、滚动七天新增数、运行总数及可用资产当前版本的对象数量；同一资产被多个图层引用只计一次。对账确认目录缺失时当前容量归零，历史版本的容量、文件清单和校验和保留。

旧资产响应以 `current_version` 表示默认版本，图层以只读的 `asset_version` 保存绑定版本。扫描和仅修改名称不改变已有图层的版本；新登记解析为资产当前版本。缺失入口的历史图层仍保留资产及版本引用，以保护文件。

`sha256` 是本地文件清单摘要：相对路径使用 `/`，按路径排序后，对每个文件记录 `{"path":...,"size":...,"sha256":...}`；按下文规范 JSON 序列化整个数组后计算 SHA-256。文件下载后据此逐文件验证；外部资源未读取时为 null。`bounds` 保存 WGS84 西、南、东、北及可选高程；跨日期变更线范围允许 west 大于 east。

资产详情保留原 `files` 清单，以 `file_checksums` 返回发布版本的逐文件指纹；版本查询同样提供该字段。服务启动时扫描受管目录并回填旧版本指纹，已捕获的指纹不可覆盖。扫描发现内容变化时保留原指纹并标为 unsafe，下载时再次核对源文件和输出快照。外部 URL 的 ready 表示登记可用，远端渲染状态由浏览器实际加载确认。

## 对象索引与空间查询

迁移`0007_object_index`后，服务启动、上传和显式对账建立按资产版本固定的索引。GeoJSON对象ID由资产ID、版本和原始Feature序号生成UUID5；原生Feature ID重复也能唯一定位，分页、重启与索引重建保持ID一致。`feature_index`为从0开始的原始Feature序号；`properties`保存原始属性，缺失的名称、高度、等级和置信度为null，数值0保留。`layer_id`返回对应默认层或最早登记层；仅有资产而未登记图层时为null，按图层查询时返回该图层ID。

`GET /api/objects`和`GET /api/objects/summary`支持`asset_id/version/layer_id/type/q/bbox/time/resolution/campus/page/page_size`。默认查询各可用资产的当前版本，按对象ID稳定排序；指定图层时使用其固定版本，版本与资产筛选冲突返回422。`q`按字面搜索ID、名称及原始属性，`type`精确匹配。`campus`选择默认图层对应校区。time须带时区；对象列表、范围选择和详情传time时附temporal={time,resolution,unit,value,missing}，resolution默认hour，可选day。原properties和几何保持，静态对象temporal为null；summary继续统计同一空间集合。

`bbox=west,south,east,north`真实筛选并裁剪返回几何，summary统计同一集合，分页只影响items。west大于east时查询日期变更线两侧；原始GeoJSON线段按原坐标连接。多边形选择请求为`{"geometry":{"type":"Polygon","coordinates":[[[113,23],[114,23],[114,24],[113,23]]]},"asset_id":"资产ID","page":1,"page_size":20}`，其余筛选字段与列表相同；同时提供bbox时取两个范围的交集。空洞和边界均参与实际几何相交，禁止用包围盒命中代替真实裁剪。无效坐标、未闭合或自交多边形返回422。

对象坐标用于定位，裁剪后重新取几何内代表点；`GET /api/objects/{id}`返回完整原始几何。summary按类型返回数量、WGS84椭球面积（平方米）与已知高度范围，未知值为null；裁剪到点或线的原始面面积为0。查询在同一数据库读快照中完成，保证并发删除时total、items和统计一致。裁剪结果只用于响应，原始文件和索引保持不变。

普通3D Tiles按资产返回一个`type="model"`、`semantic_source="geometry_model"`的资源对象，几何和语义属性为空，`feature_index=null`；它不代表独立建筑数量。缺少可查询几何的资源不参与空间筛选。外部资源只登记元信息，直接查询其对象返回409 OBJECT_INDEX_UNAVAILABLE；资产缺失或不安全返回409 ASSET_UNAVAILABLE。历史不合规GeoJSON保留资产及错误原因，索引查询返回409。

地图对象查询使用所选已加入图层的固定资产版本。前端按同一UUID5规则映射GeoJSON Feature及其多部件，列表按20条分页；地图点选清除查询条件和范围，按对象ID排序跳到该对象所在页。范围选择以100条分页完整读取`POST /api/objects/select`结果，核对总量及ID唯一性后高亮全集，列表在同一缓存集合内翻页；读取失败保留错误原因和trace_id。单对象详情始终读取原始几何。绘制期间独立接收鼠标手势，图层/版本/校区变化取消草稿并阻止旧回调提交。

专题图例与单位来自数据，静态图层`static=true`，时间切换保持同一资源实例。二维叠加层`orderable=true`；三维绘制遵循深度遮挡。

## 场景、路网与运行

路网目录使用独立的`network_versions`表，以`asset_id/version`标识JSON快照。`GET /api/networks`按路网ID、发布时间倒序和版本返回全部已发布版本的分页，默认20条、最多100条；详情未指定版本时选择最新发布且校验通过的版本。明确指定不存在版本返回404 NETWORK_NOT_FOUND；已有异常快照读取返回409 NETWORK_INVALID，`POST /api/networks/{id}/validate?version=…`仍返回200及`valid=false/issues`供诊断。问题按code稳定排序，包含实际node_ids/edge_ids。

当前校验支持无向EPSG:4326路网，坐标为经纬度及可选米制高程，边长度m、速度m/s，权重为有限正数。检查重复节点ID、重复边ID、反向重复无向边、自环、缺失节点、孤立点及连通分量。发布前校验完整结构；同ID同版本同内容幂等，不同内容409 NETWORK_VERSION_CONFLICT，修改内容须发布新版本。数据库禁止更新已存快照；并发发布使用写事务和唯一键，回滚不留下记录。内置net-001由仓库JSON启动补齐，原样保留已有版本。

场景保存完整 `camera`、`layers`、`network`、起终点、阻断边、`params`、`seed`、当前时刻和运行 ID。相机的经纬度为度，高度为米，heading/pitch/roll 为弧度；图层状态沿用 `map_attached/map_visible/map_opacity` 命名。场景可先保存未配置的路网或起终点；提交运行时必须完成有效性校验。`run_id` 作为恢复结果的引用，URL `scene/run/t` 分别引用场景、运行、时间。

场景CRUD已接入。创建版本1，创建/读取/更新均返回对应ETag；PUT完整替换后版本加一，DELETE同样要求单个带双引号的正整数If-Match。缺失返回400 IF_MATCH_REQUIRED，格式错误返回400 INVALID_IF_MATCH，过期返回409 SCENE_VERSION_CONFLICT并提供current_version。并发同版本更新仅一次成功，正文和ETag为同一次提交的快照。列表按更新时间倒序及ID稳定分页，默认20、最多100条。

场景图层以layer_id和固定资产版本定义，引用独立于全局图层登记；删除全局登记后，场景仍可读取和保存旧绑定。底图asset为null，其余层须提供存在且可用的资产版本；重复图层ID和错误默认层绑定返回422。保存不修改全局地图加入状态、显隐和透明度。场景引用在资产详情中返回type=scene、场景ID/名称/版本及asset_version；解除引用或删除场景后释放，被引用资产删除返回409。

已填写的路网版本、起终点与阻断边均须有效；未选择路网时可保存无阻断边草稿。阻断边按正式ID去重排序。current_time须带时区，保存与输出统一UTC，空值和真实0保留。输入拒绝未知字段；run_id须指向已存在的运行，未知引用返回422 RUN_NOT_FOUND。

运行请求保持原需求字段名：

```json
{"scene_id":"s1","network":{"asset_id":"net-001","version":"1.0.0"},"origin":"S","destination":"T","blocked_edges":["B-T"],"params":{"mode":"car"},"seed":0}
```

提交时原子读取当前场景版本并保存 `RunInputSnapshot`；其中 `request` 为提交参数，`scene` 为完整场景快照。请求中的路网、起终点和阻断参数作为本次实际输入，历史运行始终使用快照。请求参数有效后才创建 run；不存在的边返回 422 `INVALID_EDGE`。

- 模型固定为 `dijkstra-undirected-v1`，优化目标为总长度，预计时间为逐边 `length_m/speed_mps` 累计。长度相同按节点 ID 序列字典序确定路径。
- `net-001@1.0.0` 为合成无向路网，节点 S/A/B/C/D/T。边固定为 S-A=200、A-B=200、B-T=260、A-C=250、C-D=260、D-T=250 米；边 ID 即这些字符串，所有速度为 10 m/s。节点经纬度在校区附近合成，边长度使用显式权重，标注为合成演示。
- 基准 S→A→B→T 为 660 m、66 s；阻断 B-T 后 S→A→C→D→T 为 960 m、96 s。增幅保留计算精度 `45.454545...`，页面一位小数显示 45.5%。
- 不可达是成功运行的有效结果：`reachable=false,path=[],length_m=null,duration_s=null`；同起终点返回单节点路径、长度和时间为 0。基准不可达或长度为 0 时，增幅为 null。`rerouted` 仅在两条路径均可达且节点序列不同时为 true。
- 状态为 `queued→running→succeeded/failed/cancelled`，queued 可直接取消；重启将遗留 running 标记 failed 并写错误，queued 继续处理。取消完成后写 `finished_at`，终态不可回到排队。
- 同一 `Idempotency-Key` 与相同规范输入返回同一 run_id；同 key 不同输入返回 409。新 key 或省略 key 的再次运行产生新 run，结果保持不变。

寻路模型已接入持久队列。先以终点为源执行Dijkstra，再沿满足最短距离的邻边选择最小节点ID，得到完整节点序列字典序最小的等长路径；按显式长度的十进制表示精确累加，避免容差把略长路线误判为等长。预计时间按所选路径逐边length_m/speed_mps累计。非法节点/正式边ID返回422 INVALID_NODE/INVALID_EDGE，计算结果超出有限JSON数值范围返回422 NUMERIC_RANGE。模型计算保持原始路网。

`inputs_sha256` 由规范输入计算：先按网络版本的正式边 ID 将 `blocked_edges` 去重并升序排序，补齐 `params.mode` 和 seed 默认值；以 `{"request":规范RunInput,"scene_version":整数,"scene":SceneInput,"model_version":模型版本,"data_version":数据版本}` 为哈希对象。场景中的阻断边同样排序去重，`run_id` 只作画面引用，计算哈希时移除；场景图层按 `order`、`layer_id` 排序。使用 UTF-8、对象键递归排序、JSON 紧凑分隔符、不转义中文、不允许 NaN/Infinity；SHA-256 输出小写十六进制。run_id、submitted_at/started_at/finished_at、scene.created_at/updated_at、幂等键、trace_id 均不参与。相同输入及场景/资产/模型版本得到相同哈希；场景版本变化会产生新哈希。

运行记录保留 `run_id/status/inputs_sha256/model_version/data_version/submitted_at/started_at/finished_at/error/trace_id`，并补充 scene_id、scene_version 与 elapsed_ms。`data_version` 为 `net-001@1.0.0` 形式，图层资产版本同时留在场景快照。

队列适用于单个uvicorn服务进程，按提交时间和run_id领取排队任务，每次计算启动独立隐藏子进程。运行中取消等待该进程退出再写终态及finished_at；计算超过60秒时终止进程并保存failed/RUN_TIMEOUT。服务正常停止中断运行并保存SERVICE_STOPPED；异常退出后，下一次启动将遗留running保存为failed/RUN_INTERRUPTED，再继续queued。错误及状态日志保留首次提交的trace_id；终态更新和输入快照修改受数据库约束保护。

数据库提交后同步`storage/runs/{run_id}/input.json`、成功结果`result.json`及`run.log`，该目录通过运行接口访问。输入与结果镜像缺失时可重建，已有内容不一致返回409 RUN_ARTIFACT_CHANGED并保留现场；数据库无对应结果时报告ORPHAN_RUN_RESULT，无对应运行的目录报告ORPHAN_RUN_DIRECTORY。目录和文件链接拒绝访问。日志是可更新镜像，读取日志接口以数据库记录为准。JSON下载字节与规范result.json一致；GeoJSON导出基准/阻断路线及实际阻断边，保留run_id、输入哈希和模型/数据版本。

提交运行时独立保存场景中的资产版本引用，删除场景、移除全局图层登记或取消运行后，该历史引用继续保护源资产。资产详情返回type=run、运行ID、快照场景名称/版本及asset_version。

`GET /api/runs`按scene_id、status及带时区from/to筛选，时间包含端点并按UTC比较；from晚于to返回422 VALIDATION_ERROR。列表默认每页20、最多100，按提交时间倒序及run_id排序。

`POST /api/runs/{id}/rerun`请求体为空，原子复制旧RunInputSnapshot、inputs_sha256和资产引用，使用新run_id、trace_id及提交时间进入队列。原场景修改或删除后仍使用旧快照；旧输入和结果保持。Idempotency-Key全局复用规则与POST /api/runs相同，新记录201、同key同哈希200、不同哈希409 IDEMPOTENCY_CONFLICT。旧模型版本当前不可执行时返回409 MODEL_VERSION_UNAVAILABLE，创建前拒绝。沿用0010表结构。

资产删除冲突的message按独立引用者分类计数图层、场景与历史运行，detail.references保留逐版本明细，reference_count为明细条数。同一场景引用资产的两个版本时，计1个场景、2条明细。旧图层引用保留id/name形状；场景和运行引用增加type/version/asset_version。页面详情及冲突弹窗显示各类引用、ID与版本，并给出对应处理方式；历史运行持续保护源版本。仅被场景/运行引用的可用资产仍可重新登记图层。

仿真页已接入场景/网络分页目录、固定版本配置、If-Match保存、提交/轮询/取消及结果对比。POST结果未知时保留同一幂等键和固定请求体，重试跳过场景更新，防止场景版本变化产生另一输入。修改配置进入本地预览，后端历史结果保留；成功绘图使用RunInputSnapshot指定网络与阻断集合，路线严格取RunResult节点顺序。场景相机与图层状态独立于普通地图目录。

历史页面选择记录恢复固定快照并锁定配置；“从历史编辑”解除历史显示、复制为新场景草稿，保存创建新场景。“从历史重跑”使用rerun接口；响应未知时复用原运行目标和幂等键。JSON/GeoJSON按钮下载服务端原始字节。回放按所选路径逐边预计时间生成同一时间轴，蓝/橙标记在边内按时间插值；先到终点的标记停留。支持播放/暂停、秒数拖动、到达节点时刻步进、0.5–8倍速与复位。不可达路线无标记，同起终点为静止点；切换工作区、标签页隐藏和卸载时停止计时。

```json
{"run_id":"run-example","baseline":{"path":["S","A","B","T"],"length_m":660,"duration_s":66,"reachable":true},"blocked":{"path":["S","A","C","D","T"],"length_m":960,"duration_s":96,"reachable":true},"metrics":{"increase_percent":45.45454545454545,"rerouted":true},"created_at":"2026-10-25T04:00:01Z"}
```

## 工作区收藏与固定引用

收藏沿用 `/api/bookmarks`。`region/point` 保留原位置字段，并返回 `state=null`；`scene` 的 `region_id/longitude/latitude` 均为 null，`state` 保存以下字段：

| 字段 | 契约 |
| --- | --- |
| `page` | `map` 或 `simulation` |
| `scene_id/scene_version` | 非空场景 ID、至少为 1 的版本号 |
| `run_id` | 运行 ID 或 null，默认 null；须与捕获场景的 `run_id` 相同 |
| `time/resolution` | 带时区时间或 null，按 UTC 保存；分辨率为 `hour/day`，默认 hour |
| `camera` | 完整 `CameraState`，含位置、朝向及二维/三维模式 |
| `comparison` | 地图的 `{time,resolution}` 对照状态或 null，默认 null；time 须带时区，resolution 为 `hour/day`；仿真页面须为 null |

创建工作区收藏前保存独立的完整 Scene 快照，其图层资产由既有 `SceneAssetReference` 保护。后端在同一写事务中核对场景、版本和运行：场景不存在返回 404 `SCENE_NOT_FOUND`，版本变化返回 409 `SCENE_VERSION_CONFLICT`（detail 含 current_version），运行不存在返回 422 `RUN_NOT_FOUND`，运行与场景状态不一致返回 422 `SCENE_RUN_MISMATCH`。历史运行可关联新捕获的场景，运行自身的 `scene_id` 保持原输入。状态及对照对象的未知字段、无时区时间和位置字段混用返回 422。

全局自定义图层移除或重绑后，对象和时序查询可同时传 `layer_id/asset_id/version` 读取捕获的旧绑定。服务核对现存场景的资产引用及其 layers 中完全一致的图层 ID、资产 ID 和版本；当前目录的正常查询继续使用当前绑定。没有对应场景引用的错绑请求保持 422，未知图层保持 404；释放场景引用后，旧绑定随之失效。

`GET /api/scenes/{id}?version=1` 返回匹配的当前场景及 ETag；当前版本不符时返回上述版本冲突，场景已删除时返回 404。场景保存当前版本，调用方据此识别失效的固定引用。收藏列表保留已失效引用；改名保持 state 和 created_at，删除收藏保留关联场景与运行。

迁移 `0012_workspace_bookmarks` 为旧收藏添加 nullable JSON state。降至 `0011_timeseries` 时移除 `kind=scene` 收藏并删除 state 列，保留地区/点位收藏、其他表和发布文件；再次升级后旧收藏的 state 为 null。

## 时序与契约验收

`TimeSeriesOutput` 以 layer_id、资产版本、时刻、分辨率及单位标识一组数据。服务保存 UTC 时间，页面默认使用 Asia/Shanghai。逐小时精确选择该时次；逐日按 Asia/Shanghai 的日历日聚合当天已有小时值的算术均值，整日无值才返回缺测。示例点/线/面使用可取均值的标量专题，并在数据说明中写明单位与聚合方式。缺测对象 `{"object_id":"p1","geometry":null,"value":null,"missing":true}`；真实零值为 `value=0,missing=false`。时间切换只更新动态专题及详情。

0011保存以asset_id/asset_version为主键的unit与UTC时次→object_id→数值/null快照，禁止UPDATE，资产版本删除时级联清理。启动在对象索引后幂等播种两校区demo-points/demo-roads/demo-areas，查询只读。默认图层和同一资产版本的登记按快照识别为static=false，图例给出0/正值区间/缺测及单位，其余层保留static=true。

`GET /api/layers/{id}/times`可传asset_id/version/campus，返回已发布时次升序UTC数组；静态层为空。`GET /api/timeseries`必填layer_id/time，可传resolution=hour|day、bbox及相同版本参数；缺少快照返回409 TIMESERIES_UNAVAILABLE，不存在图层/版本返回404，绑定冲突及无时区时间返回422。bbox按对象原几何筛选并裁剪，有值项返回裁剪几何，缺测项geometry=null；对象ID保持。day响应time统一为北京时间日界对应UTC，使用IANA规则并包含历史夏令时。

合成样例的北京时间为2026-10-25、26日08:00/09:00，按此顺序：点A为0/10/20/30，B为null/12/22/32，C为5/15/null/null；道路第一条为0/100/200/300，第二条为null/120/null/null；面为0/10/null/null。点面为cm，道路为辆/小时，日值为当天已有小时值均值。第一天点A/道路第一条/面的日均分别为5/50/5，第二天面整日缺测。样例源文件和原属性保持。

地图时间轴按固定资产版本读取times/timeseries，提供小时/日、拖动、步进、复位及1×/2×/5×播放，每秒推进一个所选分辨率时次。缺测隐藏专题实体并显示文字，真实0独立着色；列表与选中详情同步temporal。动态更新复用原实体，静态资源保持；快速切换丢弃过期响应，离开工作区、标签页隐藏与卸载时停止计时。

接入各资源时覆盖：正常响应；分页无重复遗漏和旧数组兼容；缺语义及缺测；过期 If-Match；同 key 重放及输入冲突；非法边不产生 run；660/960 m、不可达和同起终点；重复运行哈希相同；重启恢复和终态取消；文件引用保护与逐文件校验。OpenAPI 随路由接入生成，最终交付时导出，字段以本模块为准。

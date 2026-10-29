# 本地图层服务

FastAPI 提供图层登记、独立文件资产管理和文件发布；SQLAlchemy 使用同步 Session；SQLite 保存元信息；Alembic 是唯一建表和迁移入口。

## 启动与配置

在本目录运行：

```powershell
uv sync --no-dev
uv run --no-dev alembic upgrade head
uv run --no-dev uvicorn app.main:app --host 127.0.0.1 --port 8000
```

OpenAPI 交互文档：<http://127.0.0.1:8000/docs>。首次启动前必须执行迁移，应用不会自动创建业务表。

默认文件布局：

```text
storage/
  catalog.db                 # 图层登记
  files/<uuid>/...           # 通过 /data-files/ 发布
  tmp/<uuid>/...             # 上传临时文件，结束时清理
  tmp/download-*/...         # 下载快照/完整 ZIP，响应结束后清理
  deleting/<uuid>/...        # 永久删除的非公开暂存目录，清理失败可重试
  runs/<uuid>/input.json     # 固定输入快照，非公开文件
  runs/<uuid>/result.json    # 成功结果，数据库提交后生成
  runs/<uuid>/run.log        # 状态日志镜像
```

可在启动和迁移前通过 PowerShell 设置 `$env:MAP_STORAGE_DIR = 'D:\city\map_back\storage'`；可选 `MAP_DATABASE_URL` 覆盖数据库连接。迁移与服务必须使用相同配置。`.env.example` 是变量说明；本服务不自动加载 `.env` 文件。

## 资产版本升级

使用新增资产版本的后端前，停止旧服务并备份 `storage/catalog.db`，再按启动章节执行 `uv run --no-dev alembic upgrade head`。迁移 `0004_asset_versions` 为现有资产原地补充 `1.0.0` 版本，为图层补齐版本引用，保留原 ID、发布地址及文件目录。

资产响应新增 `current_version`、`source_kind`、`protected`；图层响应新增只读的 `asset_version`。扫描文件和修改名称会保持已有版本绑定。版本的入口、体积、文件数及创建时间由数据库约束保持不变；删除无引用的上传资产时同时清理其版本记录。

标记为默认数据的资产禁止实体删除，返回 `403 / ASSET_PROTECTED`；图层登记仍可移除。服务启动时登记两校区共10份默认资产，文件保持在同仓库`map/public/samples`原位置，旧URL保留；部署时保留完整前后端目录。

`0005_asset_metadata` 增加名称、来源、坐标说明、逐文件 SHA-256、清单摘要和地理范围。迁移后启动服务会自动扫描受管目录、回填旧资产指纹并补录历史文件；回填后的指纹保持不变。内容被外部改动时，扫描标为路径/内容不安全，下载返回 `409 / ASSET_CONTENT_CHANGED`。下载验证发布文件及实际输出快照的逐文件内容。

`POST /api/assets/register` 登记 HTTP(S) 地址或识别已有 `/data-files/` 资产，重复地址返回409。外部地址不会被后端读取、搬移或删除，未知体积、文件数、校验和与范围返回null；删除外部资产仅删除无引用的台账记录。`GET /api/assets/{id}/versions` 和 `GET /api/assets/{id}/versions/{version}` 查询不可变版本及其入口、指纹、文件校验和与范围。详情的原 `files` 字段保留，新 `file_checksums` 提供逐文件校验。

`0006_layer_catalog` 增加自定义图层顺序、二维排序能力及默认图层状态表。`GET /api/layers/catalog?campus=university-town`返回底图、默认样例与自定义登记的统一目录；campus也可取huangpu。`PATCH /api/layers/catalog/{id}/map-state`保存加入状态、显隐、透明度与二维目标顺序。默认图层状态跨校区共用，资源始终保留在目录中；旧`/api/layers`仍只返回自定义登记。三维瓦片、拉伸面和未知远端几何遵循深度规则，排序请求返回422 ORDER_UNSUPPORTED。图层树页面按步骤10接入。

`0007_object_index`增加按资产版本固定的对象索引。服务启动、上传和显式对账建立索引，原始文件保持不变；GeoJSON按原始Feature序号生成稳定ID，普通3D Tiles记录为一个几何模型资源对象。无本地几何的外部资源保留未知计数，直接查询对象返回409并说明原因。索引可通过降级至0006再升级并重启重建，对象ID保持一致。

`0008_network_versions`保存不可变路网快照，服务启动后补齐`net-001@1.0.0`合成无向样例。`GET /api/networks`分页读取版本目录，`GET /api/networks/net-001?version=1.0.0`读取节点、边和显式权重；`POST /api/networks/net-001/validate?version=1.0.0`检查结构、重复ID/无向边、坐标、权重、缺失节点、孤立点及连通性。问题返回具体节点/边ID。版本省略时读取最新可用版本，修改内容须使用新版本；快照由数据库约束禁止覆盖。节点为校区附近合成经纬度，长度按显式m权重，速度均为10m/s。

`0009_scenes`保存完整场景及固定资产/路网版本引用。`POST /api/scenes`创建并返回ETag，GET列表/详情读取；PUT完整替换或DELETE删除均要求`If-Match: "1"`形式的当前版本，过期返回409。更新版本递增，正文与ETag一致；时间须带时区并统一输出UTC。保存场景保持全局地图状态，资产详情显示场景引用，解除引用或删除场景后释放。场景可引用已存在的运行；前端仿真页已接入配置保存、地图阻断、运行与结果对比。

寻路模型`dijkstra-undirected-v1`按显式长度求无向最短路，等长按完整节点序列字典序选择，预计时间按逐边速度累计。net-001基准660m/66s，阻断B-T后960m/96s，增幅页面口径45.5%。`uv run python tools/verify_routing.py`验证十万节点/十万边的完整模型耗时，覆盖图校验、建图、两次寻路及结果重建。

`0010_runs`增加持久队列、不可变输入/结果和历史资产引用。POST `/api/runs`提交场景ID、固定路网版本、起终点、阻断边、params和seed；同Idempotency-Key同规范输入返回原运行，输入变化返回409，新key创建新运行。GET `/api/runs`按scene_id、status、带时区from/to分页筛选历史，`/{id}`读取状态，`/{id}/input`读取快照，`/{id}/logs`读取日志，`/{id}/result`读取成功结果，`/{id}/download?format=json|geojson`导出。

POST `/api/runs/{id}/rerun`使用原运行的完整输入快照、场景/路网/模型/资产版本与inputs_sha256创建新run_id，原场景更新或删除后仍可执行。请求体为空，Idempotency-Key规则与普通提交相同：新建201，同key同哈希复用200，不同哈希409。历史模型版本当前不可执行时返回409 MODEL_VERSION_UNAVAILABLE。旧输入、结果和引用持续保留；本接口沿用0010表结构。

队列沿用本页的单进程启动方式，每次计算使用独立隐藏进程，60秒超时终止；POST `/api/runs/{id}/cancel`终止实际计算后保存cancelled，终态取消返回409 RUN_TERMINAL。异常停止后重启，遗留running标记failed/RUN_INTERRUPTED，queued继续。数据库提交后生成私有文件镜像，POST `/api/runs/reconcile`补缺失文件、报告变化及孤立目录/结果；保留异常文件供排查。删除场景或图层登记后，历史运行仍保护已固定的资产版本。降级到0009会删除运行表并清空对应Scene.run_id，场景其它字段、版本及时间保留；回退前备份整个storage目录。

`0011_timeseries`新增固定资产版本的不可变时序快照。启动时为两校区现有积水监测点、道路流量、积水范围生成合成观测；原文件与对象ID保留。GET `/api/layers/{id}/times`返回升序UTC时次，静态层返回`[]`；可用asset_id、version和campus指定绑定。GET `/api/timeseries?layer_id=demo-points&time=2026-10-25T00:00:00Z&resolution=hour`查询专题值，支持真实bbox裁剪及固定版本。每项包括object_id、geometry、value和missing，缺测为null/true，真实零为0/false；缺测项geometry为null。

小时查询精确命中请求时刻。日查询按IANA Asia/Shanghai日历日，对当天已有非null小时值取算术均值；整日缺测才返回null，响应time为北京时间当天00:00对应UTC。依赖tzdata为Windows提供时区规则。样例有2026-10-25、26日08:00/09:00四个北京时间时次；点/面单位cm，道路单位辆/小时，日值均为这些标量的日均。对象列表、范围选择及详情传time/resolution时附独立temporal字段，原properties和几何保持；静态对象temporal为null。没有时序数据的资产查询timeseries返回409 TIMESERIES_UNAVAILABLE。0011降级只移除时序表，重新升级并启动可重建同一组样例。

## API

| 方法与路径 | 内容 |
| --- | --- |
| `GET /api/health` | 进程健康状态，不代替数据库迁移检查 |
| `GET /api/bookmarks` | 读取位置收藏，按创建时间倒序 |
| `POST /api/bookmarks` | 创建地区或 WGS84 点位收藏 |
| `PATCH /api/bookmarks/{id}` | 修改收藏名称 |
| `DELETE /api/bookmarks/{id}` | 删除位置收藏 |
| `PATCH /api/layers/{id}/map-state` | 更新自定义图层加入状态、显隐或透明度 |
| `GET /api/layers` | 按创建时间降序返回图层数组 |
| `POST /api/layers` | 登记已有地址，返回 201 |
| `PATCH /api/layers/{id}` | 提交完整可编辑元信息，更新登记 |
| `DELETE /api/layers/{id}` | 删除登记，返回 204，保留文件 |
| `POST /api/layers/upload` | multipart 文件上传并登记，返回 201 |
| `GET /api/assets` | 无参数保留资产数组；显式 page/page_size 返回分页，支持 type/status/q/from/to/sort |
| `POST /api/assets/register` | 登记外部 HTTP(S) 资产元信息，重复地址返回409 |
| `GET /api/assets/{id}/versions` | 查询不可变版本、入口、范围与逐文件指纹 |
| `GET /api/assets/{id}/versions/{version}` | 查询指定版本 |
| `GET /api/assets/{id}` | 资产详情，增加相对路径和体积组成的文件清单 |
| `GET /api/assets/{id}/download` | GeoJSON 文件或完整三维发布目录 ZIP；不修改资产和登记 |
| `POST /api/assets/reconcile` | 扫描已有 UUID 发布目录，幂等补录资产、关联历史登记；返回 `{assets, discovered}` |
| `DELETE /api/assets/{id}` | 永久删除无引用资产的整个目录，成功返回 204 |
| `GET /api/objects` | 对象分页；支持资产版本、图层、类型、字面搜索、bbox及校区筛选 |
| `GET /api/objects/{id}` | 完整原始对象几何、属性、来源及资产版本 |
| `GET /api/objects/summary` | 与列表同范围的数量、面积和已知高度范围 |
| `POST /api/objects/select` | geometry为GeoJSON Polygon，其余字段与列表筛选相同；返回真实裁剪的对象分页 |
| `GET /api/stats/overview` | 资产总数、各类型数量、本地容量、滚动七天新增数与当前版本对象数；运行随对应模块接入 |
| `GET /data-files/...` | 静态文件发布 |

登记与编辑 JSON：

```json
{
  "name": "研究区建筑",
  "category": "三维模型",
  "type": "3dtiles",
  "url": "https://your-data-server.example/city/tileset.json",
  "source": "数据提供方"
}
```

类型为 `geojson` 或 `3dtiles`。`name` 最长 120 字符；`category` 最长 80；`url` 最长 2048；`source` 最长 500。响应增加 UUID `id`、`created_at`（UTC 创建时间）与只读的 `asset_id`、`asset_version`、`asset_source_kind`。已登记的外部资产同样带资产ID，旧式未登记外部地址为null。地址支持 HTTP(S) 或本服务的 `/data-files/...`，拒绝磁盘路径、凭据嵌入地址。外部资源由浏览器直接加载，远端服务需允许跨域。

图层响应还包括 `map_attached`、`map_visible`、`map_opacity`，默认 false、true、1。通过 `/api/layers/{id}/map-state` PATCH 部分或全部状态，透明度范围 0–1；状态独立于文件及登记元信息。修改地址或类型重置加入状态，删除登记同时删除其状态。

位置收藏 POST 输入：地区为 `{"name":"天河区","kind":"region","region_id":"440106"}`，点位为 `{"name":"参考点","kind":"point","longitude":113.315959,"latitude":23.121995}`。名称去除首尾空白后长 1–120；经纬度须为有限 WGS84 数值。PATCH 只接受 `name`；输出增加 `id`、UTC `created_at`，不适用的地区或坐标字段为 null。

升级到 `0003_bookmarks_map_state` 前备份 SQLite，执行 `.\.venv\Scripts\python.exe -m alembic upgrade head` 并重启后端。迁移保留旧登记和发布文件，旧登记首次加入地图后开始恢复。收藏和状态沿用当前服务器的单用户共享数据库，不依赖浏览器存储。

上传字段：`file`、`name`、`type`，以及可选 `category`、`source`、`coordinate_description`（最长1000字符）。成功后返回与地址登记相同的记录，数据地址为 `/data-files/<uuid>/...`。

数据页以XHR显示传输字节进度；传输达到100%后显示“正在校验与发布”，收到201后完成登记。传输与校验期间均可取消。服务在发布前和提交前检查断连，清理本次临时文件；发布阶段取消会回滚事务并清理本次目录。已完成的资产通过资产目录管理。

分页默认20条、上限100，筛选后返回total；体积升降序始终将外部未知容量放在最后。列表与统计读取上传/对账时的目录快照，扫描已有文件刷新磁盘变更；详情检查实际文件。from/to带时区、按UTC比较并包含端点，上传时间优先、否则使用发现时间。完整字段和错误码见[API契约](../docs/api_contract.md)。

对象查询的`bbox=west,south,east,north`真实裁剪点线面，summary使用同一集合；面积按WGS84椭球计算。单对象详情保留原始几何，缺失语义为null。分页和统计使用同一读快照，支持与无引用资产删除并发；原始文件不会被查询改写。静态对象接受带时区的time参数，时序值按步骤19接入。万对象真实HTTP性能复现：在本目录执行`uv run python tools/verify_object_queries.py`，结果写入根目录`.verification/step08-performance.json`；工具使用隔离目录和回环端口，结束后清理测试服务与临时资产。

## 文件资产与升级

`0002_assets` 为图层登记增加可空外键并创建资产台账，保留已有文件。升级并启动服务后，打开网页“我的数据 → 资产目录 → 扫描已有文件”，或在另一个 PowerShell 窗口执行一次：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/assets/reconcile
```

扫描可重复执行；原始文件名、原上传时间无法恢复时返回 null，发现时间单独记录。新上传时文件资产和图层登记在同一数据库事务中建立，失败会回滚并清理本次文件。3D Tiles 资产包含所有已发布的清单、模型、瓦片及贴图，不保留上传 ZIP。

资产记录包括 `id`、`original_name`、`type`（geojson / 3dtiles / unknown）、`entry_url`、`byte_size`、`file_count`、`uploaded_at`、`discovered_at`、`status`、`error`、`references`和 `reference_count`；旧图层引用为id/name，场景及历史运行增加type、场景版本version及asset_version。reference_count计逐版本明细条数，删除冲突message分类计独立图层/场景/历史运行数量。详情增加 `files`（相对 `path` / 字节 `size`）。状态为 active、deleting、delete_error、missing、unsafe，入口或目录缺失会显示 missing，符号链接及目录联接显示 unsafe。

同一资产可被多个登记引用。本地相对路径以及 localhost / 127.0.0.1 / ::1 的 8000、5173、4173 端口 `/data-files/...` 地址均关联相同资产，验证路径存在、类型匹配且资产可用；其他 HTTP(S) 地址作为外部地址，不访问其内容。删除登记只解除引用，文件可重新登记。

永久删除必须先解除所有引用；存在引用时返回 409，`detail` 包含 `message` 和 `references`。后端重新检查引用、标记 deleting 并阻止新引用，将整个资产目录移到不通过静态服务发布的 `deleting/` 后清理。成功文件地址返回 404；失败返回 500，保留 delete_error 和错误原因，可再次删除重试。暂存用于完成永久删除，不是用户回收站。路径根据资产 ID 映射到受管目录，拒绝越界、符号链接和 Windows 目录联接，不能删除任意磁盘文件。

SQLite 写事务保护引用检查与变更，进程内锁保护实际文件删除；本服务按单进程、单用户本机演示运行，不使用多个 uvicorn workers。引用保护针对登记直接关联的自包含资产，不解析不同资产之间的瓦片依赖。

## 文件约定

- GeoJSON：`.geojson` 或 `.json`，UTF-8（允许 BOM），不超过 10 MiB。顶层必须为 `FeatureCollection`；支持 Point、MultiPoint、LineString、MultiLineString、Polygon、MultiPolygon；允许空集合和 null geometry。
- 经纬度采用 WGS84，经度在 ±180°、纬度在 ±90°以内；坐标为有限数字。面环须闭合且至少四个位置，线至少两个位置。旧式 `crs`、GeometryCollection 和非经纬度数据需预处理。
- 3D Tiles：`.zip`，不超过 512 MiB。根目录或唯一顶层文件夹含 `tileset.json`，入口须包含 `asset.version`（1.0 / 1.1）和根包围体；保持所有子目录和资源相对路径。
- ZIP 解压总量不超过 2 GiB，条目不超过 10,000；拒绝路径越界、Windows 驱动器路径、反斜线、重复路径、符号链接和加密文件。
- 上传校验为 JSON/清单结构与归档安全校验，不进行 GLB 内容转换、完整 3D Tiles 标准认证、坐标修正或地理配准。模型实际可用性由 Cesium 渲染验证。
- 失败上传清理临时文件；数据库写入失败时清理本次发布目录。删除登记不删除发布目录；永久删除独立于“删除登记”和“从地图移除”，只允许删除无引用的受管资产。

大小上限以二进制 MiB 计算，页面简写为 MB。超限返回 413；格式或元信息无效返回 422；不存在的登记返回 404。

开发/预览优先使用 Vite 同源代理。服务另允许本机 localhost / 127.0.0.1 的 5173、4173 来源访问，便于直接登记后端数据地址。服务绑定回环地址，无登录和多用户权限。

## 测试

```powershell
uv run pytest -q
```

测试使用独立临时 SQLite 和文件目录，不修改实际 `storage/`。覆盖 CRUD、文件保留、上传双记录一致性、历史文件补录、重复扫描、多登记引用、地址关联变更、带引用删除保护、失败重试、并发删除、路径与 Windows 目录联接隔离，以及 Alembic 升降级和旧登记保留。原有上传结构、大小、ZIP 安全和失败回滚测试继续保留。当前 FastAPI/Starlette 对 httpx 测试客户端会给出一条上游弃用提示，不影响断言。

## 资产下载（2026-10-23）

下载只接受资产 ID，复用目录清单校验，拒绝缺失入口、不可用状态、越界、符号链接及目录联接。GeoJSON 创建文件快照；3D Tiles 保留全部相对路径重新打包为 ZIP，不保留或恢复原始上传包。下载快照位于非公开 tmp 目录，与永久删除共用进程锁，打包失败立即清理，文件响应结束后清理临时快照。接口不会代理外部数据，也不会新增登记、改变引用或修改原资产。后端51项测试通过，涵盖下载内容、完整目录、不可用文件、异常清理和重试。

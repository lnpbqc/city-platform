# API 1.0 · 一页接口说明

本机单用户，默认`http://127.0.0.1:8000`。前端通过同源`/api`代理调用。完整字段、约束及响应见[OpenAPI](openapi.json)与[接口契约](../api_contract.md)。

| 调用方 / 时机 | 接口 | 用途 |
| --- | --- | --- |
| 工作台启动、重连 | `GET /api/health`、`/api/version` | 健康、服务/模型/数据版本 |
| 地图初始与数据变更 | `GET /api/layers/catalog?campus=university-town` | 完整目录、固定资产版本、计数、图例与地图状态 |
| 地图开关/透明度/排序 | `PATCH /api/layers/catalog/{id}/map-state` | 保存`map_attached/map_visible/map_opacity/order` |
| 数据页上传/登记 | `POST /api/layers/upload`、`/api/layers`、`/api/assets/register` | multipart上传或登记现有/外部资源；默认资产只读 |
| 数据页浏览/详情/下载 | `GET /api/assets?page=1&page_size=20`、`/{id}`、`/{id}/versions/{version}`、`/{id}/download` | 筛选`type/status/q/from/to/sort`；详情、不可变版本和本地文件 |
| 数据页删除/对账/统计 | `DELETE /api/layers/{id}`、`/api/assets/{id}`；`POST /api/assets/reconcile`；`GET /api/stats/overview` | 登记与实体删除分开；对账显式执行；统计六项指标 |
| 对象列表/点选/范围 | `GET /api/objects`、`/{id}`、`/summary`；`POST /api/objects/select` | 固定`asset_id/version/layer_id`，支持`bbox/type/q/time/resolution`及真实多边形裁剪 |
| 时间轴 | `GET /api/layers/{id}/times`、`/api/timeseries` | 固定版本可用时次，按`time`和`resolution=hour/day`读取；缺测与0区分 |
| 推演配置与场景 | `GET /api/networks`、`/{id}?version=…`；`GET/POST /api/scenes`；`GET/PUT/DELETE /api/scenes/{id}` | 版本路网与完整场景；写入/删除场景用`If-Match: "版本号"`，固定读取加`?version=N` |
| 提交、轮询、取消、历史 | `POST/GET /api/runs`；`GET /api/runs/{id}`；`POST /{id}/cancel`、`/{id}/rerun` | 提交/重跑带`Idempotency-Key`；列表按`scene_id/status/from/to`筛选；结果未知时重试原键与输入 |
| 结果、回放与追溯 | `GET /api/runs/{id}/input`、`/result`、`/logs`、`/download?format=json` | 固定输入、结果、日志；下载另支持`geojson` |
| 完整收藏 | `GET/POST /api/bookmarks`；`PATCH/DELETE /api/bookmarks/{id}` | `kind=scene`保存工作区状态；旧地区/点位收藏保持 |

**数据规则：**GeoJSON为WGS84经纬度，高程为米；时刻使用带时区ISO 8601，接口统一UTC。分页形状为`{items,total,page,page_size}`，单页最多100；旧`GET /api/assets`不传分页时仍返回数组。资产与路网使用`asset_id@version`，发布后内容不可变。未知属性为`null`，普通3D Tiles按模型资源计数。

**错误处理：**错误体统一`{code,message,detail,trace_id}`，响应头`X-Trace-ID`对应服务日志。400参数格式、403受限/默认资源保护、404资源缺失、409引用/版本/幂等冲突、413超过上传限额、422内容/边/几何不合规、500服务异常。前端网络失败使用`NETWORK_ERROR`与`client-`诊断ID；业务错误按具体code处理，自动重连只恢复读取。

# P0需求与交付证据

依据[冻结需求](../requirements/前后端功能与验收标准.md)及[24步主计划](../../待办/待办-前后端完整功能.md)。验收使用现有校区资产、合成时序和`net-001`；香港维港、珠江新城用于定位，广州CBD转换沿README操作流程执行。

## 功能与接口

| 要求 | 验证证据 |
| --- | --- |
| 固定资产版本加载、进度和具体错误 | [地图加载](../verification/step09-map-navigation.md)、[完整复现](../verification/step22-workspace-bookmarks.md)；版本API和加载失败回归 |
| 初始范围、相机刷新、二维/三维、复位、指北与倾斜 | [导航报告](../verification/step09-map-navigation.md)中的真实相机数值和截图 |
| 经纬高、地面比例尺、三个示范区域 | 同上；读取实际地面拾取和椭球距离 |
| 六类树、空分组、显隐/透明度、计数/图例/单位 | [图层树](../verification/step10-layer-tree.md)、[时序](../verification/step20-time-axis.md) |
| 二维顺序持久化、三维保持深度 | [顺序像素与刷新验证](../verification/step10-layer-tree.md)；支持范围由原始几何确定 |
| 时间范围/当前时刻/拖动/步进/播放/暂停/1×2×5× | [时间轴](../verification/step20-time-axis.md) |
| 小时/北京时间日均、属性联动、缺测与真实0 | [时序API](../verification/step19-versioned-timeseries.md)、[时间轴](../verification/step20-time-axis.md) |
| 同视角双视图、独立时刻、静态资源复用 | [双视图](../verification/step21-dual-time-views.md)、[完整链接](../verification/step22-workspace-bookmarks.md) |
| 稳定对象ID、原始属性、来源/置信度、对象与模型区分 | [对象索引](../verification/step08-object-queries.md)、[真实交互](../verification/step11-object-interaction.md) |
| 地图/分页列表双向联动、框选/多边形、全集高亮与统计 | [135栋真实框选](../verification/step11-object-interaction.md)、[真实空间裁剪](../verification/step08-object-queries.md) |
| 上传进度、取消、300MiB、具体413/422原因 | [300MiB及取消流程](../verification/step06-data-manager.md)、最终后端回归的上传边界用例 |
| 外部登记、分页/筛选/排序、元信息/版本/指纹/范围 | [数据页](../verification/step06-data-manager.md)、[数据统计恢复](../verification/step23-reconnect-states-stats.md) |
| 场景/运行引用保护、默认/上传/外部删除语义 | [混合引用与409](../verification/step16-reference-protection.md)；原资产ID、地址和文件保持 |
| 资产/对象/运行数量、容量、类型、7天新增 | [综合统计与一致快照](../verification/step23-reconnect-states-stats.md) |
| 场景CRUD、完整相机图层参数、If-Match版本 | [场景并发](../verification/step13-versioned-scenes.md)、[仿真工作区](../verification/step17-simulation-workspace.md) |
| 不可变路网、节点/正式边ID、连通性/孤立/重复校验 | [路网版本与问题清单](../verification/step12-versioned-networks.md) |
| 确定性路径、米制长度、逐边秒数、不可达/同端点 | [手算与模型](../verification/step14-deterministic-routing.md)；[三个交付样例](run_examples/) |
| 提交/状态/取消/幂等、重复点击与未知响应 | [运行队列](../verification/step15-durable-runs.md)、[真实提交](../verification/step17-simulation-workspace.md)、[重连不重发](../verification/step23-reconnect-states-stats.md) |
| 蓝/橙/红路径与正式节点序列、660→960米/+45.5% | [地图及结果](../verification/step17-simulation-workspace.md)、[完整运行复现](../verification/step22-workspace-bookmarks.md) |
| 回放拖动/暂停/复位/节点步进与导出字节一致 | [历史与预计时间回放](../verification/step18-run-history-replay.md) |
| 历史筛选、同快照重跑、原哈希/原结果保持 | 同上；场景后来修改或删除仍可按旧输入重跑 |
| 书签含相机/图层/场景、scene/run/t新窗口一致 | [完整收藏与URL](../verification/step22-workspace-bookmarks.md) |
| 统一错误、trace、可复制诊断、自动重连与三种空态 | [重连、权限与统计](../verification/step23-reconnect-states-stats.md) |
| 持久队列、异常重启、运行输入/版本/时间/日志 | [真实进程与重启](../verification/step15-durable-runs.md)、[最终后端验收](../verification/step24-backend.md) |
| 上传/下载路径安全、符号链接/加密ZIP、默认资源保护 | 上传及资产安全回归、[最终安全实测](../verification/step24-backend.md) |
| 启动扫描/对账、固定版本引用、兼容旧API和文件 | [迁移及版本](../verification/step13-versioned-scenes.md)、[完整收藏迁移](../verification/step22-workspace-bookmarks.md) |

## 最终门槛与交接

| 要求 | 最终证据 |
| --- | --- |
| 全前后端回归、生产构建 | [前端最终报告](../verification/step24-frontend.md)、[后端最终报告](../verification/step24-backend.md) |
| 界面3秒、首屏三次中位5秒、显隐300毫秒 | 前端最终报告的实际测量表 |
| 万对象bbox100次p95≤200毫秒、十万边≤2秒、5并发无串结果 | 后端最终报告的实际测量与逐运行核对 |
| 1小时持续运行、每10分钟RSS | [稳定性记录](rss-stability.json)及最终汇总报告 |
| OpenAPI与一页接口说明 | [openapi.json](openapi.json)、[接口速查](api.md) |
| 数据ID/版本/坐标/体积/校验和 | [数据清单](data_manifest.json) |
| 正常/绕行/不可达运行输入、记录、结果与日志 | [三组实际运行](run_examples/) |
| 演示录屏 | 用户于2026-10-27明确取消，按功能交付；录屏不作为完成条件 |
| 独立源码与数据库按文档复现 | [交接复现记录](../verification/step24-handoff.md) |
| README含前后端启动及Max→FBX→modelTo3DTiles→合规ZIP | [README](../../README.md)，最终按anti-defensive-writing复查 |

文件存储沿用仓库`storage/files/{id}`、`storage/runs/{id}`布局，数据库按`asset_id@version`固定引用，保留旧发布地址。外部资源通过HTTP(S)或已有受管入口登记，其原文件由来源服务管理。黄埔原建筑存在自交时保留原数据及具体索引错误，演示对象交互使用大学城有效数据。

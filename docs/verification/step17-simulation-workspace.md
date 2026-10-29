# 步骤17：仿真推演页面验收

2026-10-26至27日，前端191项测试、类型检查和生产构建通过。后端沿用步骤16的342项结果，本步保持后端代码与迁移不变。

| 检查 | 结果 |
| --- | --- |
| 场景与目录 | 导航及直接`#/simulation`进入；读取全部分页的场景和路网版本；保存/另存及If-Match，首次延迟目录补齐、已有草稿不覆盖 |
| 固定配置 | 保存名称、路网、起终点、阻断边、seed、相机及6个图层的资产版本/加入/显隐/透明度；刷新前后场景JSON完全一致 |
| 结果 | S-A-B-T=660m/66s；阻断B-T后S-A-C-D-T=960m/96s，页面+45.5%；节点序列及指标与JSON逐项核对 |
| 地图 | 蓝色基准、橙色阻断结果及红叉；鼠标点击B-T红叉可取消/添加同名勾选；渲染保留地形/建筑深度，更新和销毁清理旧实体 |
| 防重提交 | 浏览器双击只发1次POST；刻意丢弃服务已201的响应，配置锁定，重试同key/body得到原run，总数仅增加1，场景仅保存1次 |
| 不可达及同起终点 | 阻断S-A返回空路径、长度/时间null；S→S为单节点、0m/0s、增幅null；页面分别显示不可达和起终点相同 |
| 取消 | 浏览器提交后等待running，点击取消得到cancelled及started_at/finished_at；实际计算PID退出，结果区为空 |
| 版本冲突 | 后台先更新场景，页面保存409并显示code/trace，原草稿保留；点击“读取最新场景”后读到新名称与版本 |
| 异步隔离 | 切场景/网络/卸载取消旧读取；旧结果不能覆盖新配置；取消读取输入期间切场景可释放cancelling；轮询在卸载后停止 |
| 历史保持 | 编辑预览及之后的运行保留早先成功结果，GET旧run/result与原JSON一致 |
| 完整恢复 | 实测积水点隐藏、透明度0.35；刷新后控件与服务记录一致，再保存读取实际相机，经纬高及heading/pitch/roll六项差值均0 |
| 集成审查回归 | 修复结果后改seed/再次提交清空路网、场景未恢复二维排序能力、目录未齐可提前保存；真实SFC的4项及实际GeoJSON的6项回归通过 |

浏览器使用独立storage、18000后端与15173前端，现有8000服务保持运行。正常计算用生产寻路进程；取消测试单独在隔离服务中用30秒受控慢子进程替换模型入口，沿用生产队列、父进程监视及取消逻辑。取消后同时检查API终态和实际PID退出。

代表性运行：正常阻断`1e34f51f-e324-4a49-9972-d2f499756cf8`，不可达`de1991ef-a2b1-4926-9905-995f1baf7abe`，同起终点`7b44ed6d-b9fa-4bfe-9f6d-3b72fe88461a`，取消`aee247d8-e0c4-4231-ada3-13b5919774d1`。这些ID属于隔离验收数据。

截图：

- [路径对比](../../output/playwright/step17-result.png)
- [不可达](../../output/playwright/step17-unreachable.png)
- [同起终点](../../output/playwright/step17-same-endpoint.png)
- [场景版本冲突](../../output/playwright/step17-scene-conflict.png)
- [运行中取消](../../output/playwright/step17-cancelled.png)
- [目录加载期间的配置锁](../../output/playwright/step17-loading-guard.png)
- [修改seed后的草稿路网](../../output/playwright/step17-seed-preview.png)

复现：map目录执行`pnpm test`和`pnpm build`。API与状态用例位于tests/simulationApi.test.mjs、tests/simulation.test.mjs，真实SFC集成位于tests/simulationWorkspace.test.mjs，路线顺序及拾取/清理位于tests/simulationGeometry.test.mjs和tests/mapController.test.mjs。README、前后端说明、API契约及本报告已按anti-defensive-writing复查，保留合成权重、受控慢进程和历史页面后续范围。

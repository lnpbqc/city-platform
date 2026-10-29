# 步骤24：前端最终验收

Windows、Edge 143、Node 24环境；现有大学城本地资产，浏览器缓存禁用，视口1600×1000。最终前端247项通过，类型检查与生产构建通过。

| 指标 | 三次实测/范围 | 结果 |
| --- | --- | --- |
| 生产图层树出现 | 413 / 253 / 342 ms | 均≤3秒 |
| 生产本地资产首屏 | 3375 / 3691 / 4227 ms | 中位3691 ms≤5秒 |
| 生产建筑显隐 | 16.0–28.5 ms | ≤300 ms |
| 开发模式首屏 | 4652 / 5332 / 5741 ms | 中位5332 ms |

首屏口径为从导航开始至五个已加入资源ready，再等待两次动画帧；生产模式使用独立15174预览及18000隔离API。开发模式数据保留作对照，性能验收采用生产构建。

功能证据见[完整收藏](step22-workspace-bookmarks.md)、[断开恢复](step23-reconnect-states-stats.md)和[需求矩阵](../delivery/acceptance-matrix.md)。用户于2026-10-27明确取消录屏，录屏已停止并删除，不作为本次完成条件。

截图：[生产首屏](../../output/playwright/step24-production-first-screen.png)。原始记录位于`.verification/step24-frontend-tests.log`、`step24-build.log`、`step24-performance-ui.log`及`step24-production-ui.log`。
